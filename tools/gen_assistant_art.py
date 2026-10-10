"""用中转站的图像模型生成小助手「米迦尔」的逐帧原画（v1.7 卡 C3 的正式美术通道）。

与 ``gen_placeholder_sprites.py``（程序化占位帧）互补：这里调 OpenAI 兼容的
``/v1/images/generations``，按 clip 逐帧出图，原图落 ``work/assistant_art/``
（草稿区，gitignore），再由 ``tools/pack_assistant_sprites.py`` 缩成 48×48 精灵表。

密钥**只从环境变量读**（``BD_IMAGE_API_KEY``），不进参数、不进日志、不进文件。

用法::

    set BD_IMAGE_API_KEY=...
    python tools/gen_assistant_art.py --probe                 # 只探模型是否可用
    python tools/gen_assistant_art.py --clip sit --frames 4
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work" / "assistant_art"
BASE_URL = os.environ.get("BD_IMAGE_BASE_URL", "https://linkai.pics/v1")
KEY_ENV = "BD_IMAGE_API_KEY"


def _headers(extra: dict | None = None) -> dict:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise SystemExit(f"缺环境变量 {KEY_ENV}")
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
         "User-Agent": "BlockDirector-assistant-art/1.0"}
    h.update(extra or {})
    return h


def call(model: str, prompt: str, size: str, timeout: float) -> dict:
    body = json.dumps({"model": model, "prompt": prompt, "size": size, "n": 1}).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}/images/generations", data=body, headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def call_responses(chat_model: str, deployment: str, prompt: str, size: str, quality: str,
                   timeout: float, image_b64: str = "") -> dict:
    """经 ``/v1/responses`` 的 image_generation 工具出图（中转站上游是 Azure 部署，
    部署名走 ``x-ms-oai-image-generation-deployment`` 头）。返回 ``{"b64_json": ...}``。
    ``image_b64`` 非空时作为参考图一起发（PNG/JPEG 的 base64）。"""
    content = [{"type": "input_text", "text": prompt}]
    if image_b64:
        content.append({"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"})
    #: 部署名两处都给：头（Azure 直连形态）＋ 工具 ``model`` 字段（部分中转只认这个）。
    tool = {"type": "image_generation", "model": deployment, "size": size, "quality": quality}
    body = json.dumps({"model": chat_model, "input": [{"role": "user", "content": content}],
                       "tools": [tool], "tool_choice": {"type": "image_generation"}}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/responses", data=body,
        headers=_headers({"x-ms-oai-image-generation-deployment": deployment}))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    for item in data.get("output") or []:
        if item.get("type") == "image_generation_call" and item.get("result"):
            return {"b64_json": item["result"], "usage": data.get("usage")}
    raise RuntimeError(f"responses 未返回图像：output 类型 {[i.get('type') for i in data.get('output') or []]}")


def save_image(item: dict, path: Path, timeout: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if item.get("b64_json"):
        path.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=timeout) as resp:
            path.write_bytes(resp.read())
    else:
        raise RuntimeError(f"响应里没有图像数据：{sorted(item)}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成小助手原画")
    parser.add_argument("--model", default="gpt-image-2-5")
    parser.add_argument("--via", choices=("images", "responses"), default="responses")
    parser.add_argument("--chat-model", default="gpt-5.6-luna")
    parser.add_argument("--quality", default="low")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--timeout", type=float, default=400.0)
    parser.add_argument("--prompt", default="")
    parser.add_argument("--out", type=Path, default=OUT / "probe.png")
    parser.add_argument("--probe", action="store_true", help="出一张测试图，报告耗时与响应形状")
    args = parser.parse_args(argv)

    prompt = args.prompt or ("pixel art, a small cute cyan fox mascot sitting, purple ear tips, "
                             "yellow lightning mark on forehead, white belly, orange eyes, flat background")
    t0 = time.time()
    try:
        if args.via == "responses":
            item = call_responses(args.chat_model, args.model, prompt, args.size, args.quality, args.timeout)
            data = {"usage": item.pop("usage", None), "data": [item]}
        else:
            data = call(args.model, prompt, args.size, args.timeout)
    except urllib.error.HTTPError as exc:
        print(f"[HTTP {exc.code}] {exc.read()[:400].decode('utf-8', 'replace')}")
        return 2
    item = (data.get("data") or [{}])[0]
    save_image(item, args.out, args.timeout)
    print(f"[OK] {args.model} {round(time.time() - t0)}s keys={sorted(item)} "
          f"usage={data.get('usage')} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
