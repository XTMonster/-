"""规则元信息目录（v1.7 卡 A4 / TDD §7 末段）。

单一真源（id / severity / summary），供 sidecar 的 ``GET /v1/ui/rules`` 与
Web 前端消费。**方向单向**：``rule_checker.py`` / ``compliance.py`` 不 import
本模块——这里是元信息，检查器不感知。

18 条 = ``rule_checker.py``（R001–R012、R019）＋ ``compliance.py``
（R013–R017）。``COMPOSITION`` 构图门**不收**：它不是 ``R\\d{3}`` 形态，
也不可被 ``rules_disabled`` 关闭。
"""

from __future__ import annotations

from typing import Any, Dict, List

RULES: List[Dict[str, Any]] = [
    {"id": "R001", "severity": "error",
     "summary": "轴线一致性：越轴/轴线重建未拍出/中性机位连用（双级：error＋warning 并存，E_AXIS_001）"},
    {"id": "R002", "severity": "error",
     "summary": "角色与墙体/道具穿模（AABB 膨胀 0.2，E_SPACE_001）"},
    {"id": "R003", "severity": "error",
     "summary": "同一角色动作时间重叠（E_SDL_001）"},
    {"id": "R004", "severity": "warning",
     "summary": "相机对准点落在视锥之外（E_CAM_001）"},
    {"id": "R005", "severity": "warning",
     "summary": "角色不在画面内（E_CAM_001）"},
    {"id": "R006", "severity": "error",
     "summary": "镜头时长非法（E_SDL_001）"},
    {"id": "R007", "severity": "error",
     "summary": "镜头引用不存在角色/无可用相机（E_SDL_001）"},
    {"id": "R008", "severity": "warning",
     "summary": "角色位于地面以下或悬空（E_SPACE_001）"},
    {"id": "R009", "severity": "warning",
     "summary": "机位距离与景别期望偏差超容差（E_CAM_001）"},
    {"id": "R010", "severity": "warning",
     "summary": "相邻镜同景别同角度缺乏变化（E_AXIS_001）"},
    {"id": "R011", "severity": "error",
     "summary": "对白排布超出镜头时长（E_SDL_001）"},
    {"id": "R012", "severity": "warning",
     "summary": "两人同框朝向同号未成正反打/眼高差超限（E_CAM_001）"},
    {"id": "R013", "severity": "warning",
     "summary": "视线（gaze）与 SceneBrief 声明不符（strict 升降：compliance.py:156 strict→ERROR；E_SCRIPT）"},
    {"id": "R014", "severity": "warning",
     "summary": "运镜声明合法性（strict 升降：compliance.py:91；E_SCRIPT）"},
    {"id": "R015", "severity": "error",
     "summary": "镜数/时长/景别分布合规（COUNT/DURATION 恒 ERROR：compliance.py:214/:258；order 与 SHOT_TYPE 子支 strict 升降）"},
    {"id": "R016", "severity": "error",
     "summary": "台词归属合规（:302 恒 ERROR；:312 新编台词 strict 升降）"},
    {"id": "R017", "severity": "warning",
     "summary": "空镜合规（恒 WARNING：:139）"},
    {"id": "R019", "severity": "warning",
     "summary": "银幕方向跨镜翻转且无中性机位过渡（strict 升降：rule_checker.py:834 三元形态）"},
]
