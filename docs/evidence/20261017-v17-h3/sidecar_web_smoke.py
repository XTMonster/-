"""H3-② sidecar＋Web 3 镜样例冒烟（一次性证据脚本）。

起真实 sidecar（web-root=仓库 web/），探测关键端点并落报告 JSON：
  - 静态：GET /、/static/app.js、/static/polish.js
  - UI 只读：GET /v1/ui/rules、/v1/ui/events?since=0、/v1/ui/config
  - polish 通道：POST /v1/ui/script/polish（无上游时 502 结构化容错）、
                POST /v1/ui/script/polish/accept（缺 run_id → 400 形状）
  - 鉴权：无 token 时 /v1/ui/* 应为 401

纯 stdlib。脚本自身不 commit。
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SIDECAR = ROOT / "tools" / "sidecar_server.py"
OUT = Path(__file__).resolve().parent / "sidecar_web_smoke.json"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request(method: str, url: str, body: dict | None = None,
             token: str = "") -> tuple:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read()
            payload = {}
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                payload = {"_text": raw.decode("utf-8", "replace")[:200]}
            return response.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        payload = {}
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            payload = {"_text": raw.decode("utf-8", "replace")[:200]}
        return exc.code, payload


def main() -> int:
    port = _free_port()
    token = "bd-h3-smoke-token"
    proc = subprocess.Popen(
        [sys.executable, str(SIDECAR), "--port", str(port),
         "--token", token, "--web-root", str(ROOT / "web"),
         "--upstream-kind", "openai", "--upstream", "http://127.0.0.1:9",
         "--model", "smoke-model"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    report = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "base": base, "checks": {}}
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(base + "/", timeout=2)
                break
            except Exception:
                time.sleep(0.25)
        else:
            report["checks"]["server_start"] = {"ok": False,
                                                "reason": "sidecar 未能启动"}
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        report["checks"]["server_start"] = {"ok": True}

        # --- 静态（免鉴权） ---
        status, payload = _request("GET", base + "/", token="")
        report["checks"]["index"] = {"ok": status == 200,
                                     "status": status,
                                     "has_title": "BlockDirector" in str(payload.get("_text", ""))}
        for asset in ("/static/app.js", "/static/polish.js", "/static/pixel.css"):
            status, _ = _request("GET", base + asset, token="")
            report["checks"][asset] = {"ok": status == 200, "status": status}

        # --- 鉴权：无 token → 401 ---
        status, _ = _request("GET", base + "/v1/ui/rules", token="")
        report["checks"]["auth_required"] = {"ok": status == 401, "status": status}

        # --- 带 token 的 UI 只读端点 ---
        for path in ("/v1/ui/rules", "/v1/ui/events?since=0",
                     "/v1/ui/config", "/v1/ui/state_map",
                     "/v1/ui/knowledge/stats"):
            status, payload = _request("GET", base + path, token=token)
            report["checks"][path] = {"ok": status == 200, "status": status,
                                      "shape": sorted(payload.keys())[:8]}

        # --- polish 通道 ---
        status, payload = _request(
            "POST", base + "/v1/ui/script/polish", token=token,
            body={"script": "镜号：1\n拍摄手法：固定镜头\n角色：米迦尔"})
        # 无真实上游 → 502 结构化 error（E2 良定义：不崩溃、形状固定）
        report["checks"]["polish_no_upstream"] = {
            "ok": status in (200, 502), "status": status,
            "has_error_field": "error" in payload}

        status, payload = _request(
            "POST", base + "/v1/ui/script/polish/accept", token=token,
            body={"run_id": ""})
        # 空 run_id → 400（良定义）
        report["checks"]["polish_accept_bad_run"] = {
            "ok": status == 400, "status": status,
            "error": payload.get("error", "")}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    ok = all(item.get("ok", False)
             for key, item in report["checks"].items() if key != "server_start")
    report["overall"] = "PASS" if ok else "FAIL"
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
