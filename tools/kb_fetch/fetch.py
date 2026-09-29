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
FETCHED = common.WORK / "fetched.jsonl"
FETCH_REJECTS = common.WORK / "fetch_rejects.jsonl"
RESOLVED = common.WORK / "sources.resolved.json"
ROBOTS_DIR = common.WORK / "robots"


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _http_get(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "text/plain,*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def robots_allows(url: str, timeout: float, cache_dir: pathlib.Path = ROBOTS_DIR) -> Tuple[bool, str]:
    """按 robots.txt 判定；拿不到 robots.txt 时**拒绝**（宁缺勿滥）。"""
    parsed = urllib.parse.urlsplit(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / (parsed.netloc.replace(":", "_") + ".txt")
    if cache_file.exists():
        text = cache_file.read_text(encoding="utf-8", errors="replace")
    else:
        try:
            raw = _http_get(robots_url, timeout)
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


def _cache_path(digest: str) -> pathlib.Path:
    return common.RAW_DIR / f"{digest}.txt"


def fetch_source(source: Dict, timeout: float, rate_seconds: float,
                 sleeper=time.sleep) -> Dict:
    """返回 `{source_ref, text, mode, domain, genre, cache_path}` 或抛 FetchError。"""
    url = str(source["url"])
    mode = str(source["mode"])
    if mode == "manual":
        if not url.startswith(common.OWNWORK_SCHEME):
            raise FetchError(f"manual 来源的 url 必须用 {common.OWNWORK_SCHEME}：{url}")
        rel = url[len(common.OWNWORK_SCHEME):]
        path = (common.ROOT / rel).resolve()
        if not str(path).startswith(str(common.ROOT.resolve())):
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
