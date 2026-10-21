"""当前场景的上下文单例（供工具层读写）。

场景建好之后，工具（查询/角色/相机）需要知道"现在有哪些角色、当前是哪台
相机、轴线是哪条"。把这些放进一个薄上下文，避免工具去猜对象命名。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..cinema.axis import Axis
from ..cinema.subjects import resolve_subjects
from ..contracts.cast import SceneSpec
from ..contracts.plan import Plan


@dataclass
class SceneContext:
    characters: Dict[str, Any] = field(default_factory=dict)     # id → Character
    #: v1.3 §3.6：群众代理对象。**刻意不进 characters**——角色面板、场景
    #: 状态、构图评分与标签都按 characters 遍历，混进去这四处会一起失真。
    crowd: List[Any] = field(default_factory=list)
    vfx: Dict[str, Any] = field(default_factory=dict)            # vfx_id → 对象
    cameras: Dict[str, Any] = field(default_factory=dict)        # shot_id → camera 对象
    shot_types: Dict[str, str] = field(default_factory=dict)     # shot_id → 景别
    schedule: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # shot_id → (起, 止)
    plan: Optional[Plan] = None
    spec: Optional[SceneSpec] = None      # §13.1 的角色管理要写回这里
    current_shot_id: str = ""
    axis: Optional[Axis] = None
    #: 方案 B（§3.6.5）：逐镜预演时跨镜累积的轴状态机。``build_scene`` 的
    #: 第二趟用局部变量，逐镜 ``rebuild_shot`` 必须把同一状态持久化在这里，
    #: 否则修 shot_N 会把 shot_N+1 的轴侧推乱。
    axis_live_side: Optional[int] = None
    axis_spans: Dict[str, Any] = field(default_factory=dict)
    #: 方案 B：扫线翻转（live_side 更新）只在该镜**第一次**预演时发生；
    #: 同一镜的修复/回滚重建沿用已记录的侧别，不再重复翻转（迭代是增量
    #: 调整，不是重跑全片状态机）。
    axis_advanced_shots: set = field(default_factory=set)
    notes: List[str] = field(default_factory=list)
    #: R11 / T4：runtime_world_state.json 的落盘路径（driver 建 run 目录后
    #: 登记；未登记 = 不写盘，零行为差）。
    world_state_path: Optional[str] = None
    #: 缺陷 B / T6：每镜的最高分世界状态快照（shot_id → payload），
    #: 由 driver 在 ReAct 新高时写入；revert_shot 工具从这里取回滚目标。
    react_best_snapshot: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def character(self, character_id: str):
        return self.characters.get(character_id)

    def camera_for(self, shot_id: str = ""):
        key = shot_id or self.current_shot_id
        return self.cameras.get(key)

    def camera_by_name(self, name: str):
        for camera in self.cameras.values():
            if getattr(camera, "name", "") == name:
                return camera
        return None

    def shot(self, shot_id: str = ""):
        """取镜头计划（默认当前镜头）。"""
        if self.plan is None:
            return None
        key = shot_id or self.current_shot_id
        for shot in self.plan.shots:
            if shot.shot_id == key:
                return shot
        return None

    def require_character_in_shot(self, character_id: str) -> Optional[str]:
        """v1.6 A3（D-17）：检查角色是否在本镜出场角色中。

        对不在场的主体做动作是环境/氛围节拍的常见误用（如把"干鱼串飘动"
        当成角色动画）。返回错误信息；``None`` 表示通过。
        """
        shot = self.shot()
        if shot is None:
            return "没有当前活动镜头"
        present = set(str(cid) for cid in (getattr(shot, "characters", None) or []))
        if str(character_id) not in present:
            roster = ", ".join(sorted(present)) or "（无）"
            return (f"{character_id} 不在本镜在场角色 {{{roster}}} 里。"
                    f"环境/氛围节拍请用 vfx 字段（vfx_type 闭集见 create_vfx）。")
        return None

    def subjects_for(self, shot_id: str = "") -> List[Any]:
        """本镜的**被摄主体**：镜头自己声明的角色。

        构图评分与规则判定必须共用同一份主体集合。v1.2 的
        ``check_composition`` 工具直接拿 ``character_list``（全剧组）去评分，
        于是画面里的第三个人会被当成主体——实测两人相对而立时，单人镜的
        搭档离机位更近、显得更大，评分从 71 掉到 40，修复循环被完全带偏。

        v1.4 X9：**有镜头计划时不再回退整个剧组**——镜头没显式声明角色就该有
        "没有主体"的结论，而不是把全剧组拉进来（那会让空镜/无声明镜头混进
        R012 的正反打判定）。只有**完全没有计划**（计划外的临时调用）时才
        保留"全剧组"这一历史行为。
        """
        shot = self.shot(shot_id)
        return resolve_subjects(shot, self.character_list,
                                has_plan=self.plan is not None)

    @property
    def character_list(self) -> List[Any]:
        return list(self.characters.values())


_active: Optional[SceneContext] = None


def set_context(context: Optional[SceneContext]) -> None:
    global _active
    _active = context


def get_context() -> Optional[SceneContext]:
    return _active


def clear_context() -> None:
    global _active
    _active = None
