"""管线第 1 步：抓取 / 读取来源（执行文档 v1.4 §2.3c）。

* `mode: http` —— 只按 robots.txt 允许的路径抓取，带 User-Agent、限速，
  按 sha256 落缓存（`work/raw/<sha256>.txt`），**绝不**绕付费墙、不登录、不抓整部剧本/字幕。
* `mode: manual` —— 读仓库内的自撰笔记（`repo://knowledge/source_notes/*.md`），
  许可为 `OwnWork`，`sha256` 就是笔记正文的哈希（可独立复算）。

幂等：同一个 sha256 的结果会被复用（含第一次记录的 `retrieved_at`），
所以重复运行不产生新条目（§2.3d「按 sha256 幂等」）。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Sequence, Tuple

try:  # 允许 `python -m tools.kb_fetch.fetch` 与直跑两种入口
    from . import common
except ImportError:  # pragma: no cover - 直跑时
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common  # type: ignore

USER_AGENT = ("BlockDirectorBot/1.4 (previs knowledge corpus; "
              "contact: local operator; +https://www.gutenberg.org/)")
#: §2.3c「绝不抓取」：只允许走 http/https。没有这道白名单，`sources.yaml`
#: 里一条 `file:///C:/Windows/win.ini` 就能把本机文件读成语料（`urlopen`
#: 原生支持 file/ftp/data）。
ALLOWED_SCHEMES = ("http", "https")
#: 一次抓取允许跟随的重定向跳数；每一跳都要重新过 robots 与 scheme。
MAX_REDIRECTS = 5
FETCHED = common.WORK / "fetched.jsonl"
FETCH_REJECTS = common.WORK / "fetch_rejects.jsonl"
RESOLVED = common.WORK / "sources.resolved.json"
ROBOTS_DIR = common.WORK / "robots"


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _scheme_of(url: str) -> str:
    return urllib.parse.urlsplit(url).scheme.lower()


def _require_scheme(url: str) -> str:
    """只放行 http/https；其余（file/ftp/data/…）一律是 §2.3c 的拒收项。"""
    scheme = _scheme_of(url)
    if scheme not in ALLOWED_SCHEMES:
        raise FetchError(f"scheme_not_allowed:{scheme or 'none'}:{url}")
    return scheme


def _robots_cache_file(cache_dir: pathlib.Path, netloc: str) -> pathlib.Path:
    """robots 缓存文件名只允许 ``[A-Za-z0-9._-]``。

    netloc 来自外部输入（`sources.yaml`），它允许反斜杠与点；直接拼进路径时
    ``work/robots/..\\..\\evil.txt`` 在 Windows 上会写到仓库根目录之外。
    这里把非法字符全部折成 ``_``，并拒绝空名，路径因此永远留在 `cache_dir` 内。
    """
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(netloc)).strip("._") or "unknown"
    return cache_dir / f"{safe[:120]}.txt"


def robots_allows(url: str, timeout: float, cache_dir: Optional[pathlib.Path] = None,
                  _seen: Optional[Sequence[str]] = None) -> Tuple[bool, str]:
    """按 robots.txt 判定；拿不到 robots.txt 时**拒绝**（宁缺勿滥）。"""
    # 默认值必须在**调用时**解析 `ROBOTS_DIR`：写成 `cache_dir=ROBOTS_DIR`
    # 会把默认参数绑定到导入那一刻的对象，测试的 monkeypatch 会静默失效，
    # 结果就是单元测试写到仓库真实的 `work/robots/`。
    cache_dir = pathlib.Path(cache_dir or ROBOTS_DIR)
    parsed = urllib.parse.urlsplit(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = _robots_cache_file(cache_dir, parsed.netloc)
    if cache_file.exists():
        text = cache_file.read_text(encoding="utf-8", errors="replace")
    else:
        seen = tuple(_seen or ())
        if parsed.netloc in seen:
            # robots.txt 之间互相重定向（A→B→A）会无限递归；直接判未取到。
            return False, "robots_loop"
        try:
            raw = _http_get(robots_url, timeout, robots_seen=seen + (parsed.netloc,))
        except Exception as exc:  # noqa: BLE001 - 明确记因由并拒收
            return False, f"robots_unavailable:{type(exc).__name__}"
        text = raw.decode("utf-8", errors="replace")
        cache_file.write_text(text, encoding="utf-8", newline="\n")

    path = parsed.path or "/"
    applies = False
    disallowed: List[str] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            applies = value == "*" or "blockdirectorbot" in value.lower()
        elif key == "disallow" and applies and value:
            disallowed.append(value)
    for rule in disallowed:
        if path.startswith(rule):
            return False, f"robots_disallow:{rule}"
    return True, ""


class _RobotsAwareRedirect(urllib.request.HTTPRedirectHandler):
    """跟随重定向前，对**目标 URL**重跑 scheme 白名单与 robots 门。

    只用 `urlopen` 默认行为时，`/start` 一条 302 就能把抓取带到
    `robots.txt` 明令禁止的路径上——实测 `Disallow: /private/` 会被整条绕过
    （见 `tests/test_kb_pipeline.py::test_redirect_hop_must_pass_robots_again`）。
    """

    max_redirections = MAX_REDIRECTS
    max_repeats = 2

    def __init__(self, timeout: float, robots_seen: Sequence[str] = ()) -> None:
        super().__init__()
        self._timeout = timeout
        self._robots_seen = tuple(robots_seen)

    def _check(self, url: str) -> None:
        _require_scheme(url)
        allowed, reason = robots_allows(url, self._timeout, _seen=self._robots_seen)
        if not allowed:
            raise FetchError(f"redirect_{reason}")

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        self._check(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _http_get(url: str, timeout: float, robots_seen: Sequence[str] = ()) -> bytes:
    _require_scheme(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "text/plain,*/*"})
    opener = urllib.request.build_opener(_RobotsAwareRedirect(timeout, robots_seen))
    with opener.open(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def _cache_path(digest: str) -> pathlib.Path:
    return common.RAW_DIR / f"{digest}.txt"


def fetch_source(source: Dict, timeout: float, rate_seconds: float,
                 sleeper=time.sleep) -> Dict:
    """返回 `{source_ref, text, mode, domain, genre, cache_path}` 或抛 FetchError。"""
    url = str(source["url"])
    mode = str(source["mode"])
    # `fetch_source` 也可以被单独调用（脚本/测试），不能依赖调用方先建目录——
    # 否则缓存写入会 FileNotFoundError，把"目录没建"伪装成"来源有问题"。
    common.ensure_work_dirs()
    if mode == "manual":
        if not url.startswith(common.OWNWORK_SCHEME):
            raise FetchError(f"manual 来源的 url 必须用 {common.OWNWORK_SCHEME}：{url}")
        rel = url[len(common.OWNWORK_SCHEME):]
        path = (common.ROOT / rel).resolve()
        # 用相对路径判定而不是 `str(path).startswith(str(ROOT))`：前缀比较会把
        # 兄弟目录也算成"仓库内"——`../白模预演codex_evil/x.md` 解析后
        # `E:\白模预演codex_evil\x.md` 恰好以 `E:\白模预演codex` 开头，
        # 于是任意相邻目录里的文件都会被当成 OwnWork 语料读进来。
        if not path.is_relative_to(common.ROOT.resolve()):
            raise FetchError(f"manual 来源越出仓库：{url}")
        if not path.is_file():
            raise FetchError(f"manual 来源文件不存在：{rel}")
        text = path.read_text(encoding="utf-8")
        digest = common.sha256_text(text)
        cache_file = _cache_path(digest)
        if not cache_file.exists():
            cache_file.write_text(text, encoding="utf-8", newline="\n")
        retrieved_at = str(source.get("retrieved_at") or
                           _dt.date.fromtimestamp(path.stat().st_mtime).isoformat())
    elif mode == "http":
        # 先过 scheme 白名单，再去问 robots：否则 `file:///C:/x` 这类来源会先
        # 走到 `robots_allows`（它对任何 scheme 都会拼一条 robots URL），
        # 把一个"来源非法"的问题伪装成"robots 取不到"。
        _require_scheme(url)
        allowed, reason = robots_allows(url, timeout)
        if not allowed:
            raise FetchError(reason)
        sleeper(rate_seconds)
        raw = _http_get(url, timeout)
        digest = common.sha256_bytes(raw)
        cache_file = _cache_path(digest)
        if not cache_file.exists():
            cache_file.write_bytes(raw)
        text = raw.decode("utf-8", errors="replace")
        retrieved_at = str(source.get("retrieved_at") or _now_iso())
    else:  # dataset
        raise FetchError(f"mode={mode!r} 尚未支持（本版只用 http/manual）")

    source_ref = {
        "url": url,
        "title": str(source["title"]),
        "author": str(source["author"]),
        "license": str(source["license"]),
        "retrieved_at": retrieved_at,
        "sha256": digest,
    }
    return {
        "source_ref": source_ref,
        "mode": mode,
        "domain": str(source["domain"]),
        "genre": str(source.get("genre", "") or ""),
        "theme": str(source.get("theme", "") or ""),
        "note": str(source.get("note", "") or ""),
        "cache_path": _display_path(cache_file),
        "chars": len(text),
        "text": text,
    }


class FetchError(RuntimeError):
    pass


def _display_path(path: pathlib.Path) -> str:
    """尽量用仓库相对路径（测试里缓存可能落在临时目录）。"""
    try:
        return str(path.relative_to(common.ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _resolved_key(url: str, digest: str) -> str:
    return f"{url}::{digest}"


def run(sources: Sequence[Dict], timeout: float = 30.0, rate_seconds: float = 1.0,
        only: str = "") -> Tuple[List[Dict], List[Dict]]:
    common.ensure_work_dirs()
    previous: Dict[str, Dict] = {}
    if RESOLVED.exists():
        previous = json.loads(RESOLVED.read_text(encoding="utf-8"))

    fetched: List[Dict] = []
    rejects: List[Dict] = []
    resolved: Dict[str, Dict] = {}
    for source in sources:
        if only and only not in (common.source_slug(source), source.get("domain")):
            continue
        try:
            record = fetch_source(source, timeout, rate_seconds)
        except FetchError as exc:
            rejects.append({"url": source.get("url"), "domain": source.get("domain"),
                            "reason": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 - 网络错误也要留痕
            rejects.append({"url": source.get("url"), "domain": source.get("domain"),
                            "reason": f"{type(exc).__name__}: {exc}"})
            continue
        key = _resolved_key(record["source_ref"]["url"], record["source_ref"]["sha256"])
        old = previous.get(key)
        if old:  # 幂等：复用第一次的 retrieved_at，重跑不漂
            record["source_ref"]["retrieved_at"] = old["source_ref"]["retrieved_at"]
        resolved[key] = record
        fetched.append(record)

    for key, record in previous.items():  # 保留历史解析结果，供断点续跑
        resolved.setdefault(key, record)

    # 中间产物带正文：`work/` 已被 .gitignore 忽略，步骤之间因此可以独立重跑。
    common.write_jsonl(FETCHED, fetched)
    common.write_jsonl(FETCH_REJECTS, rejects)
    common.dump_json(RESOLVED, resolved)
    return fetched, rejects


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.fetch")
    parser.add_argument("--sources", default=str(common.SOURCES_YAML))
    parser.add_argument("--only", default="", help="只跑某个 domain 或 slug")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--rate", type=float, default=1.0, help="同域两次请求的最小间隔（秒）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    sources = common.load_sources(pathlib.Path(args.sources))
    fetched, rejects = run(sources, args.timeout, args.rate, args.only)
    print(json.dumps({"fetched": len(fetched), "rejects": len(rejects),
                      "rejects_detail": rejects}, ensure_ascii=False))
    return 0 if fetched else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
