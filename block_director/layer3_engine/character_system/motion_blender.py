"""动作混合器门面（执行文档 v1.2 §9.7）。

对上提供"加动作 → 校验 → 烘焙"的线性用法；混合数学与冲突仲裁在
``block_director/motion/model.py``（纯计算，已被单测覆盖）。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ...motion.model import ActionRequest, check_conflicts
from ...utils.logger import get_logger
from ...utils.threading_guard import main_thread_only
from .motion_library import BakeResult, apply_motions

log = get_logger("motion-blender")


class MotionBlender:
    """把一个角色的多个动作按图层合成并烘焙。"""

    def __init__(self, character) -> None:
        self.character = character
        self.requests: List[ActionRequest] = []
        self._counter = 0

    def add(self, action_type: str, start_frame: int, end_frame: int,
            **params) -> ActionRequest:
        self._counter += 1
        request = ActionRequest(
            action_type=action_type,
            start_frame=int(start_frame),
            end_frame=int(end_frame),
            params=dict(params),
            character_id=self.character.id,
            action_id=f"{self.character.id}_{action_type}_{self._counter}",
        )
        self.requests.append(request)
        return request

    def validate(self) -> List[str]:
        return check_conflicts(self.requests)

    @property
    def layer_summary(self) -> Dict[str, int]:
        summary: Dict[str, int] = {}
        for request in self.requests:
            summary[request.layer] = summary.get(request.layer, 0) + 1
        return summary

    @main_thread_only("MotionBlender.bake")
    def bake(self, *, clear: bool = True,
             interpolation: str = "BEZIER",
             base_pose: Optional[Dict[str, object]] = None,
             trace_end: Optional[int] = None) -> BakeResult:
        return apply_motions(self.character, self.requests,
                             clear=clear, interpolation=interpolation,
                             base_pose=base_pose, trace_end=trace_end)
