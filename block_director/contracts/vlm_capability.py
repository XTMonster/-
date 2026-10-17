"""VLM 评委能力探测（卡 V3 §1）——纯函数、无 bpy。

``contracts/vlm_review.py::review_shot`` 返回的每条记录不外乎三种结局，
这里把它折成"主模型能不能看图"的结论：

* ``status == "ok"`` ⇒ 这次真的评过 ⇒ 支持图像输入（True）；
* skipped 且 ``error`` 点名"不支持图像 / 多模态"这类拒收文案 ⇒ 不支持（False）；
* 其余（超时、429、524、缺字段）⇒ 无法下结论（None）——**不缓存**，
  下一镜继续当探测。

探测是"第一次真实评审"本身，因此本模块**不另发请求**：它只读评审记录。
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

#: 拒收图像输入的 error 文案闭集（不区分大小写，逐字来自卡 V3 §1）。
#: 2026-10-10 追加：DeepSeek V4 Pro 官方口返回 200 但思考里写
#: ``[Unsupported Image]`` / ``I can't view the image``——同样要判为不支持。
IMAGE_UNSUPPORTED_PHRASES: Tuple[str, ...] = (
    "image_url", "image input", "vision", "multimodal",
    "does not support image", "不支持图像", "unsupported content type",
    "unsupported image", "i can't view the image",
)


def classify_capability(record: Mapping[str, Any]) -> Optional[bool]:
    """把一条评审记录折成能力结论：True 支持 / False 不支持 / None 未定。"""
    if not isinstance(record, Mapping):
        return None
    if record.get("status") == "ok":
        return True
    error = record.get("error")
    if record.get("status") == "skipped" and isinstance(error, str):
        lowered = error.lower()
        if any(phrase.lower() in lowered
               for phrase in IMAGE_UNSUPPORTED_PHRASES):
            return False
    return None
