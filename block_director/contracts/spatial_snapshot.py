"""空间理解与设计快照契约（spatial-understanding-json Ticket 02-04；纯层，禁 bpy）。

与 ``contracts/spatial_ruler.py``（空间尺观测扩展契约，审核用）是姊妹层：
这里是**空间事实层**——前向设计快照 / 后向观测快照 / 偏差报告三份版本化 JSON
的 Python DTO 单真源与偏差阈值 registry。

约定的形状（serde 往返即逐位一致）：

* 每个定量字段统一 ``{"value", "unit", "provenance"}`` 三件套；解不出 = ``None``，
  并在所属条目的 ``unresolved[]`` 列出字段名——**不猜**、不引入第五种 provenance；
* provenace 四态复用 ``contracts/spatial_ruler.py::PROVENANCE_STATES``
  （``script_declaration / plan_intent / algorithmic_measurement / blender_geometry``），
  本模块不重复定义；
* 只增不改：不与既有 ``spatial_digest`` / ``spatial-ruler-observation`` 契约冲突。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .spatial_ruler import PROVENANCE_STATES  # noqa: F401  # 复用，重导出


#: 前向设计快照的契约版本。Python DTO 是单真源，JSON Schema 由测试钉住一致
#: （落盘路径见 ``contracts/spatial_snapshot/schema/``，Ticket 06）。
DESIGN_SNAPSHOT_SCHEMA = "spatial-understanding-design/v1"
#: 后向观测快照的契约版本（Ticket 03 使用）。
OBSERVATION_SNAPSHOT_SCHEMA = "spatial-understanding-observation/v1"
#: 设计 vs 实测偏差报告的契约版本（Ticket 04 使用）。
DIFF_SNAPSHOT_SCHEMA = "spatial-understanding-diff/v1"

#: 偏差阈值 registry（单一真源，消费者一律从本模块导入；Ticket 04 落进偏差文档
#: 的 ``registry`` 字段供证据对照）。默认值一次写清、不散落在代码各处。
DIFF_THRESHOLDS: Dict[str, float] = {
    "position_m": 0.35,          # 角色/物品位置偏差（米）
    "facing_deg": 25.0,          # 朝向夹角（度）
    "gaze_deg": 25.0,            # 视线向量夹角（度）
    "motion_path_m": 0.5,        # 运动首末位移差（米）
    "motion_speed_m_s": 0.5,     # 运动速度差（米/秒）
    "camera_position_m": 0.5,    # 机位位置偏差（米）
    "camera_rotation_deg": 10.0,  # 机位朝向夹角（度）
}


def registry_payload() -> Dict[str, Any]:
    """偏差阈值的 JSON 载荷（写进快照/偏差文档的 ``registry`` 字段）。"""
    return {
        "diff_thresholds": dict(DIFF_THRESHOLDS),
        "units": {"m": "meters", "deg": "degrees", "m_s": "meters/second"},
    }


def _deep_plain(value: Any) -> Any:
    """递归还原为普通 dict/list，保证 ``to_dict == 原 JSON``。"""
    if isinstance(value, dict):
        return {key: _deep_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_plain(item) for item in value]
    return value


@dataclass
class DesignSnapshot:
    """前向空间设计快照：内存中保真持有整个 JSON，属性给出类型化读取。

    ``from_dict`` / ``to_dict`` 双向逐字段一致；含 ``$schema`` 头字段在内的
    未知可选字段保留（沿用 ``ObservationBundle`` 的做法）。
    """

    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, source: Dict[str, Any]) -> "DesignSnapshot":
        return cls(data=copy.deepcopy(source))

    def to_dict(self) -> Dict[str, Any]:
        return _deep_plain(self.data)

    @property
    def schema_version(self) -> str:
        return str(self.data.get("schema_version", ""))

    @property
    def run_context(self) -> dict:
        return self.data.get("run_context") or {}

    @property
    def shot_ids(self) -> List[str]:
        return list(self.data.get("shot_ids") or [])

    @property
    def characters(self) -> List[Dict[str, Any]]:
        return self.data.get("characters") or []

    @property
    def props(self) -> List[Dict[str, Any]]:
        return self.data.get("props") or []

    @property
    def anchors(self) -> List[Dict[str, Any]]:
        return self.data.get("anchors") or []

    @property
    def camera_intents(self) -> List[Dict[str, Any]]:
        return self.data.get("camera_intents") or []


__all__ = [
    "DESIGN_SNAPSHOT_SCHEMA",
    "OBSERVATION_SNAPSHOT_SCHEMA",
    "DIFF_SNAPSHOT_SCHEMA",
    "DIFF_THRESHOLDS",
    "PROVENANCE_STATES",
    "registry_payload",
    "DesignSnapshot",
]
