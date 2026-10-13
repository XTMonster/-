"""判官（spec §15.2/15.4）：mock 离线确定性 / real OpenAI 兼容。

mock 只证明管线通（evidence_grade=plumbing），真实提升证据只认
judge=real:<model>（evidence_grade=ab_result）。报告必须标注判官种类，
防止把 mock 结果当成真实提升。
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any, Dict, Optional

from .schemas import demo_args_for


_MEASURE_RE = re.compile(
    r"-\s*(?P<key>headroom|lead_room|thirds|balance|framing)[^:]*:"
    r"\s*(?P<val>-?[\d.]+)")
_SCORE_RE = re.compile(r"总分:\s*(?P<val>[\d.]+)")

_KEY_BY_METRIC = {
    "headroom": "headroom_current",
    "thirds": "thirds_current",
    "balance": "balance_current",
    "lead": "lead_current",
}


class MockJudge:
    """确定性判官：尺子臂按读数作答，基线臂给固定猜测。

    2×2 四臂（spec §15.2）：
    * baseline       —— 无数值、无方法：固定猜测；
    * ruler          —— 有读数、无方法：完美读数读者；
    * method         —— 有方法、无数值：方法论读者（方向用默认方向，数值仍猜）；
    * ruler_method   —— 有读数+方法：完美读数 + 方法（上界）。

    这是 plumbing 用的"完美读者"，不是效果证据；它让四臂在转录里
    产生真实不同的答案分布，从而验证聚合/对拍/报告链路真的在区分各臂。
    """

    name = "mock"
    evidence_grade = "plumbing"
    model: Optional[str] = None

    def parse_measurements(self, block: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "headroom_current": None, "lead_current": None,
            "thirds_current": None, "balance_current": None,
            "framing_current": None, "score": None,
        }
        for m in _MEASURE_RE.finditer(block):
            key = _KEY_BY_METRIC.get(m.group("key"))
            if key is not None:
                out[key] = float(m.group("val"))
        m = _SCORE_RE.search(block)
        if m:
            out["score"] = float(m.group("val"))
        return out

    def _direction_from_measurements(self, comp: str,
                                     m: Dict[str, Any]) -> Optional[str]:
        if comp == "headroom" and (m.get("headroom_current") or 0.0) > 0.12:
            return "抬高机位"
        if comp == "lead_room" and m.get("lead_current") is not None \
                and m["lead_current"] < 0.645:
            return "平移"
        if comp == "rule_of_thirds" and (m.get("thirds_current") or 1.0) > 0.105:
            return "平移"
        if comp == "balance" and (m.get("balance_current") or 0.0) > 0.0:
            return "左右平衡"
        if comp == "occlusion":
            return "平移"
        if comp == "framing" and (m.get("framing_current") or 0.0) < 0.9:
            return "推近"
        return None

    def answer(self, task, prompt: str, arm: str) -> Dict[str, Any]:
        gt = task.ground_truth
        kind = task.kind
        uses_measurements = arm in {"ruler", "ruler_method"}
        uses_method = arm in {"method", "ruler_method"}
        m = self.parse_measurements(prompt) if uses_measurements else {}

        if kind == "verdict":
            return {"passed": bool(gt["passed"]), "failed": list(gt["failed"])}
        if kind == "estimate":
            metric = task.payload.get("metric")
            if uses_measurements and metric is not None:
                v = m.get(_KEY_BY_METRIC[metric])
                if v is not None:
                    return {"value": v}
            # 无数值：基线/方法臂都只能猜测（plumbing，非证据）
            return {"value": 0.5}
        if kind == "direction":
            comp = task.payload.get("component")
            if uses_measurements and comp is not None:
                d = self._direction_from_measurements(comp, m)
                if d is not None:
                    return {"direction": d}
            if uses_method and comp is not None:
                # 方法论读者：无读数时按"多数失败分量靠横向调度"的默认方向，
                # 仅用于 plumbing 制造可分解的四臂差异，不是效果证据。
                return {"direction": "平移"}
            return {"direction": "收紧景别"}  # 基线：固定猜测
        if kind == "fix":
            # 03b：处方白名单首选的工具 + demo schema 可执行的最小参数样本
            #（参数不参与对拍，只保证评分器的 args_executable 判真）。
            return {"tool": gt["tool"], "tool_args": demo_args_for(gt["tool"])}
        if kind == "prescription_verdict":
            return {"accept": bool(gt["accept"]), "reason": "mock-plumbing"}
        if kind == "dynamic_facts":
            return {
                "exits": list(gt["exits"]),
                "reentries": list(gt["reentries"]),
                "direction_changes": int(gt["direction_changes"]),
                "hero_bands": list(gt["hero_bands"]),
            }
        return {}


def _strip_fences(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    return content.strip()


class RealJudge:
    """OpenAI 兼容判官：urllib 直连，零第三方依赖。

    环境变量：SR_EVAL_API_BASE / SR_EVAL_API_KEY / SR_EVAL_MODEL。
    输出必须是纯 JSON；解析失败重试并最终记为 parse_error（判定为错）。
    """

    name = "real"
    evidence_grade = "ab_result"

    def __init__(self, api_base: str, api_key: str, model: str,
                 timeout: int = 90) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _parse_json(self, content: str) -> Dict[str, Any]:
        text = _strip_fences(content)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise ValueError(f"答案里没有 JSON 对象: {content[:200]!r}")
            return json.loads(match.group(0))

    def _call(self, prompt: str, use_format: bool) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": "你是空间构图评审。只输出 JSON，不输出任何解释。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        if use_format:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return json.loads(data["choices"][0]["message"]["content"])

    def answer(self, task, prompt: str, arm: str) -> Dict[str, Any]:
        last: Optional[Exception] = None
        for use_format in (True, False):
            for _ in range(2):
                try:
                    raw = self._call(prompt, use_format)
                    return self._parse_json(
                        raw if isinstance(raw, str) else json.dumps(raw))
                except Exception as exc:  # noqa: BLE001 —— 判官必须对任何异常兜底
                    last = exc
        return {"parse_error": str(last)}
