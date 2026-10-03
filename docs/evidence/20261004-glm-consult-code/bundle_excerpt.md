下面是我们**现在**的源码摘录（`block_director/cinema/axis.py:104-196`，逐字复制）：

```python
@dataclass(frozen=True)
class CrossingEvent:
    """一次配对连线的变化（纯计划推算的结果）。

    * `rotated_deg`：这一镜里连线转过的角度（大 = 走位把它重建了）；
    * `flip`：转过 90° 以上 ⇒ **左右真的换了个儿**（侧别要翻）；
    * `visible`：这一镜里两人**同框**（观众看得见这次变化 ⇒ 合法桥接）。
    """

    shot_id: str
    visible: bool          # 变化是不是发生在**两人同框**的那一镜里
    people: Tuple[str, str]
    rotated_deg: float = 0.0
    flip: bool = False


def crossing_events(axis: Axis, plan, initial: Dict[str, Sequence[float]]
                    ) -> Dict[str, CrossingEvent]:
    from .schedule import travelled_positions

    left, right = axis.left_label, axis.right_label
    if not left or not right:
        return {}
    before = travelled_positions(plan, dict(initial))
    direction = axis.direction
    if direction == (0.0, 0.0):
        return {}
    out: Dict[str, CrossingEvent] = {}
    shots = list(getattr(plan, "shots", []) or [])
    for index, shot in enumerate(shots):
        shot_id = str(shot.shot_id)
        start = before.get(shot_id) or {}
        following = before.get(str(shots[index + 1].shot_id)) if index + 1 < len(shots) else None
        end = following or _after_own_walks(shot, start)
        a_start, b_start = start.get(left), start.get(right)
        a_end, b_end = end.get(left), end.get(right)
        if not (a_start and b_start and a_end and b_end):
            continue
        rotated = _rotation_deg(a_start, b_start, a_end, b_end)
        if rotated >= 0.5:
            out[shot_id] = CrossingEvent(
                shot_id=shot_id,
                visible=len([cid for cid in (shot.characters or [])
                             if str(cid) in (left, right)]) >= 2,
                people=(left, right),
                rotated_deg=rotated,
                flip=rotated >= 90.0)
    return out


def _rotation_deg(a_start, b_start, a_end, b_end) -> float:
    fx0, fy0 = float(b_start[0]) - float(a_start[0]), float(b_start[1]) - float(a_start[1])
    fx1, fy1 = float(b_end[0]) - float(a_end[0]), float(b_end[1]) - float(a_end[1])
    n0 = math.hypot(fx0, fy0)
    n1 = math.hypot(fx1, fy1)
    if n0 < EPS or n1 < EPS:
        return 0.0
    cosine = max(-1.0, min(1.0,
                           (fx0 / n0) * (fx1 / n1) + (fy0 / n0) * (fy1 / n1)))
    return math.degrees(math.acos(cosine))


def axis_state(axis: Axis, plan, initial) -> Dict[str, int]:
    sides: Dict[str, int] = {}
    if not axis.left_label or not axis.right_label:
        return sides
    events = crossing_events(axis, plan, initial)
    side = int(axis.established_side) or SIDE_POSITIVE
    for shot in getattr(plan, "shots", []) or []:
        shot_id = str(shot.shot_id)
        sides[shot_id] = side
        event = events.get(shot_id)
        if event is not None and event.visible and event.flip:
            side = -side
    return sides
```

另外（不在上面的摘录里，但判据用到）：规则侧 `rule_checker._axis_rebuild` 计算
**规范首镜线**与**当前派生线**的夹角 `angle`，并令
`bridged = 本镜机位中性(落在线上) or 存在 visible 且 rotated_deg ≥ 5° 的镜头`；
`angle ≥ 30°` 时，`bridged` 为真就报警告、为假就报**错误**（越轴）；
构建器摆机位时用的是 `axis_state` 给出的侧别 ＋ 当前连线。
