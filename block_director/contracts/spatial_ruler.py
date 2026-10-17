"""空间尺观测扩展契约（Ticket 01 纯接口层，无 bpy）。

对应 ``.scratch/spatial-ruler-json/`` 的 schema 与 contract.v2.json：

- 常量（处方 allow-list、来源四态）与 schema/既有测试保持一致；
- :class:`ObservationBundle`：样例 JSON ↔ DTO 双向 round-trip，逐字段保留
  （含 ``$schema``/``$id`` 等头字段与 ``note`` 等可选字段）；
- :func:`validate_bundle`：对 bundle 的语义校验（schema 之外）：未知处方
  操作、悬空测量引用、非法来源、verdict 缺数值对。

约定：本模块只 import stdlib 与同层 contracts，绝不 import ``bpy``。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


#: 处方可执行操作白名单（schema + 契约 v2 单一真源，不另抄第二份）。
PRESCRIPTION_OPERATIONS = frozenset({
    "retime_shot", "restore_cast", "reframe", "move_character",
    "change_camera_side", "review_transition",
})

#: 来源四态（schema ``#/$defs/provenance``）。
PROVENANCE_STATES = frozenset({
    "script_declaration", "plan_intent",
    "algorithmic_measurement", "blender_geometry",
})


@dataclass
class Measurement:
    """单条测量记录（契约 v2 ``measurements[]`` 的 DTO）。

    字段形状与 ``.scratch/spatial-ruler-json/examples/*.v2.json`` 逐项对齐；
    ``source == provenance`` 由 :mod:`.cinema.ruler_measure` 的调用方保证，
    语义校验由 :func:`validate_bundle` 负责。``to_dict`` 产出普通 dict，
    ``None`` 可选字段省略——round-trip 后与样例逐字段一致。
    """

    measurement_id: str
    shot_id: str
    metric: str
    value: Any
    unit: str
    source: str
    provenance: str
    transition_id: Optional[str] = None
    subject_id: Optional[str] = None
    frame: Optional[Any] = None
    expected: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {key: value for key, value in {
            "measurement_id": self.measurement_id,
            "shot_id": self.shot_id,
            "transition_id": self.transition_id,
            "subject_id": self.subject_id,
            "frame": self.frame,
            "metric": self.metric,
            "value": self.value,
            "expected": self.expected,
            "unit": self.unit,
            "source": self.source,
            "provenance": self.provenance,
        }.items() if value is not None}


class _AttrDict(dict):
    """dict 子类：支持属性访问，用于 measurement/verdict 等单条记录。

    目的：DTO 的 ``bundle.measurements[0].source`` 这种读法与 round-trip
    逐字段一致（包括未知的可选字段）同时成立；``to_dict`` 仍产出普通 dict。
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class Measurement(dict):
    """单条观测测量记录（契约 v2 ``#/$defs/measurement``）。

    dict 子类：既支持 ``m["metric"]`` 下标访问（``ruler_measure.py`` 的
    ``{m["metric"]: m for m in measurements}`` 组装），也天然满足
    ``isinstance(item, dict)``（``validate_bundle`` 的引用闭合检查）。
    必须字段与 schema 一一对应；``note`` 可选，缺省不落键。
    """

    REQUIRED = (
        "measurement_id", "shot_id", "metric", "value",
        "unit", "source", "provenance",
    )

    def __init__(self, *, measurement_id: str, shot_id: str, metric: str,
                 value: Any, unit: str, source: str, provenance: str,
                 transition_id: Any = None, subject_id: Any = None,
                 frame: Any = None, expected: Any = None,
                 note: str = "") -> None:
        super().__init__(
            measurement_id=str(measurement_id),
            shot_id=str(shot_id),
            metric=str(metric),
            value=value,
            unit=str(unit),
            source=str(source),
            provenance=str(provenance),
        )
        if transition_id is not None:
            self["transition_id"] = transition_id
        if subject_id is not None:
            self["subject_id"] = subject_id
        if frame is not None:
            self["frame"] = frame
        if expected is not None:
            self["expected"] = expected
        if note:
            self["note"] = note


def _deep_plain(value: Any) -> Any:
    """把 ``_AttrDict`` 递归还原为普通 dict/list，保证 ``to_dict == 原 JSON``。"""
    if isinstance(value, dict):
        return {key: _deep_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_plain(item) for item in value]
    return value


def _records(values: Any) -> List[_AttrDict]:
    return [_AttrDict(item) for item in (values or [])]


@dataclass
class ObservationBundle:
    """观测契约 bundle：内存中保真持有整个 JSON，属性给出类型化读取。

    ``from_dict``/``to_dict`` 双向逐字段一致（测试钉住：round-trip 后
    再经 jsonschema 校验仍通过，且与原始样例逐字段相等）。
    """

    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, source: Dict[str, Any]) -> "ObservationBundle":
        return cls(data=copy.deepcopy(source))

    def to_dict(self) -> Dict[str, Any]:
        return _deep_plain(self.data)

    @property
    def schema_version(self) -> str:
        return str(self.data["schema_version"])

    @property
    def observation_id(self) -> str:
        return str(self.data["observation_id"])

    @property
    def run_context(self) -> dict:
        return self.data.get("run_context") or {}

    @property
    def plugin_adapter(self) -> dict:
        return self.data.get("plugin_adapter") or {}

    @property
    def observation_request(self) -> dict:
        return self.data.get("observation_request") or {}

    @property
    def registry(self) -> dict:
        return self.data.get("registry") or {}

    @property
    def shot_specs(self) -> List[_AttrDict]:
        return _records(self.data.get("shot_specs"))

    @property
    def camera_specs(self) -> List[_AttrDict]:
        return _records(self.data.get("camera_specs"))

    @property
    def measurements(self) -> List[_AttrDict]:
        return _records(self.data.get("measurements"))

    @property
    def verdicts(self) -> List[_AttrDict]:
        return _records(self.data.get("verdicts"))

    @property
    def prescriptions(self) -> List[_AttrDict]:
        return _records(self.data.get("prescriptions"))


def validate_bundle(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """语义校验（schema 之外）：返回可定位的 findings 列表，空表 = 通过。

    校验项：
    - ``unknown_operation``：处方 operation 不在 allow-list；
    - ``dangling_reference``：verdict.evidence / 处方前后置引用的
      measurement_id 不存在；
    - ``illegal_provenance``：measurement/camera_spec 的 source/provenance
      不在来源四态；
    - ``verdict_missing_numeric_pair``：verdict 缺 expected/actual/threshold/unit。

    findings 形状：``{"code", "message", "path"}``，供上层直接定位。
    """

    findings: List[Dict[str, Any]] = []
    measurements = list(data.get("measurements") or [])
    measurement_ids = {str(item.get("measurement_id") or "")
                       for item in measurements if isinstance(item, dict)}

    for index, item in enumerate(measurements):
        if not isinstance(item, dict):
            continue
        for key in ("source", "provenance"):
            if item.get(key) not in PROVENANCE_STATES:
                findings.append({
                    "code": "illegal_provenance",
                    "message": f"来源非法：{key}={item.get(key)!r}（不在来源四态）",
                    "path": f"measurements[{index}].{key}",
                })

    for index, camera in enumerate(data.get("camera_specs") or []):
        if not isinstance(camera, dict):
            continue
        if camera.get("source") not in PROVENANCE_STATES:
            findings.append({
                "code": "illegal_provenance",
                "message": f"来源非法：source={camera.get('source')!r}（不在来源四态）",
                "path": f"camera_specs[{index}].source",
            })

    for index, verdict in enumerate(data.get("verdicts") or []):
        if not isinstance(verdict, dict):
            continue
        for key in ("expected", "actual", "threshold", "unit"):
            if key not in verdict:
                findings.append({
                    "code": "verdict_missing_numeric_pair",
                    "message": f"verdict 缺 {key}：判定必须带 expected/actual/threshold/unit",
                    "path": f"verdicts[{index}].{key}",
                })
        for ref in verdict.get("evidence") or []:
            if ref not in measurement_ids:
                findings.append({
                    "code": "dangling_reference",
                    "message": f"verdict 引用了不存在的测量：{ref!r}",
                    "path": f"verdicts[{index}].evidence",
                })

    for index, prescription in enumerate(data.get("prescriptions") or []):
        if not isinstance(prescription, dict):
            continue
        operation = prescription.get("operation")
        if operation not in PRESCRIPTION_OPERATIONS:
            findings.append({
                "code": "unknown_operation",
                "message": f"未知处方操作：{operation!r}（allow-list 不允许）",
                "path": f"prescriptions[{index}].operation",
            })
        for key in ("precondition_measurement_ids",
                    "postcondition_measurement_ids"):
            for ref in prescription.get(key) or []:
                if ref not in measurement_ids:
                    findings.append({
                        "code": "dangling_reference",
                        "message": f"处方 {key} 引用了不存在的测量：{ref!r}",
                        "path": f"prescriptions[{index}].{key}",
                    })
    return findings
