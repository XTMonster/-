"""中文分镜表解析（v1.3 执行计划 附录 C）。

**为什么需要它**：用户实际交给插件的往往是**分镜表**（镜号 / 拍摄手法 /
拍摄距离 / 角色 / 画面内容 / 预估时长），而不是 Fountain 叙事剧本。
v1.2 只会把它当纯文本，于是"镜号、景别、时长"这些**导演已经写死的约束**
全部丢失，模型只能自己重新规划——实测把 6 个镜号压成 2 个、把声明 33 秒
的片子规划成 39.5 秒、还改写了台词。

本模块把这些声明**结构化**成 :class:`ParsedShotDeclaration`，交给
:class:`ParsedScript` 携带；后续的 R015/R016 就是拿计划与场景去核对它们。

设计约束：

* 纯解析，不依赖 bpy、不调用 LLM（"声明"必须能在离线状态下拿到）；
* **永不致命**：任何一步失败都降级为纯文本路径并记告警，
  绝不因为格式不标准就拒绝一份剧本；
* 声明的时长与文本**只作声明**——它们不参与排片，排片真源仍是
  ``ShotPlan.duration_frames``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .model import (
    ParsedAction,
    ParsedDialogue,
    ParsedNodeDeclaration,
    ParsedScene,
    ParsedScript,
    ParsedShotDeclaration,
)
from .timing import DURATION_SUFFIX_RE, extract_declared_seconds, frames_from_seconds

#: 时长的单位：``秒`` 与 ``s/sec/secs/seconds`` 是同一样东西的两种写法。
#: 用户的真实剧本（`码头市场_电影级分镜_v10.docx` 家族）通篇写 ``5s``、
#: ``（12s）``，v1.4 的解析器只认 ``秒``，于是**声明时长被整批丢掉**
#: （实测 13 个镜号全报"没有「预估时长」声明"）——这等于把导演写死的
#: 时长硬约束换成了模型的猜测，是**降级**，不是"容错"。
_DURATION_UNIT = r"(?:秒|seconds?|secs?|s)"

#: 节点标题：允许 markdown 的 ``#`` 前缀，也允许 ``**节点1：…**（12s）``
#: 这种"加粗 ＋ 括号里写总时长"的排版写法。
NODE_HEADER_RE = re.compile(
    r"^\s*(?:[#]+\s*)*[*]*\s*节点\s*(?P<num>\d+)\s*[：:]\s*(?P<rest>.*)$")
#: 节点总时长：``总时长：12秒`` / ``总时长：12s`` / ``（12s）`` 三种写法等价。
NODE_TOTAL_RE = re.compile(
    r"(?:总时长\s*[：:]\s*|[（(]\s*)"
    r"(?P<sec>\d+(?:\.\d+)?)\s*" + _DURATION_UNIT)

#: 镜号行
SHOT_HEADER_RE = re.compile(r"^\s*镜号\s*[：:]\s*(?P<num>\d+)\s*$")

#: 分镜表字段。刻意枚举而不是"任意 ``xx：yy``"——否则台词行会被误吃成字段。
FIELD_KEYS = ("镜号", "机号", "拍摄手法", "技巧", "地点", "时间", "角色",
              "画面内容", "背景内容", "音效", "灯光", "预估时长",
              "拍摄视角", "拍摄距离", "角色位置", "构图技巧", "氛围", "作用")
FIELD_RE = re.compile(
    r"^\s*(?P<key>" + "|".join(FIELD_KEYS) + r")\s*[：:]\s*(?P<value>.*)$")

#: 台词：``米迦尔（自信）："伊恩，这里就交给我吧！"（约3秒）``
#: 引号要求是**必需**的，否则"角色：米迦尔、伊恩"这类字段会被当成台词。
_DIALOGUE_BODY = (
    # 说话人里不允许出现句读与引号——否则"伊恩按住他的肩。米迦尔：…"这种
    # 行内写法会把整句话当成名字（v1.4 D-1 实测踩到过）。
    r"(?P<speaker>[^（(：:\s。！？；，、,.!?;\"'“”]{1,12})"
    r"(?:[（(](?P<emotion>[^）)]*)[）)])?\s*[：:]\s*"
    r"[\"“](?P<text>.+?)[\"”]\s*")

#: 台词后面的时长注记：``（约3秒）`` / ``(3s)``。行内匹配用它而不是
#: ``(?P<tail>.*)$``——贪婪到行尾会把同一行里的第二句台词整段吃掉。
_DURATION_TAIL = (
    r"\s*(?P<duration>(?:[（(]\s*约?\s*\d+(?:\.\d+)?\s*"
    r"(?:秒|s|sec|seconds?)\s*[）)])?)")

#: 行首台词（一行就是一句台词）。行首这一支保留"引号之后随便跟什么"的宽尾，
#: 因为小结行、多个时长注记都可能跟在后面。
DIALOGUE_RE = re.compile(r"^\s*" + _DIALOGUE_BODY + r"(?P<tail>.*)$")

#: v1.4 D-1：**行内**台词。``画面内容：米迦尔："我先上船。"`` 这种写法在
#: 真实分镜表里很常见，而 v1.3 只匹配行首，于是整行被 ``FIELD_RE`` 吃掉、
#: 台词凭空消失。``finditer`` 用来在同一行里同时认出字段与台词。
INLINE_DIALOGUE_RE = re.compile(_DIALOGUE_BODY + _DURATION_TAIL)

#: ``0-3秒`` / ``2.5-4 秒``
TIMECODE_RE = re.compile(
    r"(?P<start>\d+(?:\.\d+)?)\s*[-–~]\s*(?P<end>\d+(?:\.\d+)?)\s*秒")

#: **不带说话人**的台词行：``台词："伊恩，这里就交给我吧！"（2.75s，自信语速4字/秒）``。
#: 这是 ``码头市场_电影级分镜_v10.docx`` 家族的写法——说话人不在这一行，而在**同一分镜的
#: 「角色」字段**里。v1.4 会把行首那两个字当成一个叫"台词"的角色（实测：整份剧本的
#: 说话人集合 = {台词}，「角色：米迦尔」于是被 `_split_characters` 全部过滤掉，
#: 13 个镜号一个角色都没有——那是**降级**，不是"认不出就少认几个"）。
QUOTED_LINE_RE = re.compile(
    r"^\s*台词\s*[：:]\s*(?P<quote>[\"“](?P<text>.+?)[\"”])\s*(?P<tail>.*)$")

#: 「角色」字段里明显**不是角色**的写法（背景群众、路人编号…）。只用来整条剔掉，
#: 不用来猜名字。
_ROLE_BACKGROUND_MARKERS = ("路人", "背景", "人群", "群众", "商贩", "旁观",
                            "无角色", "无人", "众人", "若干")

#: ``预估时长：5秒`` / ``预估时长：5s`` 的值
SECONDS_RE = re.compile(r"(?P<sec>\d+(?:\.\d+)?)\s*" + _DURATION_UNIT)

#: 小结行：只作交叉校验，不产生新的声明
SUMMARY_RE = re.compile(
    r"^\s*[-*]?\s*(台词总时长|动作与?特效总时长|动作总时长|总计)\s*[：:]")

#: 拍摄距离 → 景别（§10.5 的九宫格）
DISTANCE_TO_SHOT = (
    ("大特写", "ECU"), ("手部特写", "CU"), ("面部特写", "CU"),
    ("特写", "CU"), ("近景", "MCU"), ("中远景", "MLS"), ("中景", "MS"),
    ("过肩", "OTS"), ("大远景", "ELS"), ("远景", "LS"), ("全景", "LS"),
)

#: 拍摄手法 → 运镜 id（v1.3 的运镜封闭清单里的名字）
INSTRUCTION_TO_MOVE = (
    ("快速推", "dolly_in"), ("推镜", "dolly_in"), ("推", "dolly_in"),
    ("拉", "dolly_out"), ("跟拍", "follow_subject"), ("跟随", "follow_subject"),
    ("环绕", "orbit_cw"), ("摇", "pan_right"), ("升降", "crane_up"),
    ("固定", "static"),
)


@dataclass
class ShotList:
    """一份分镜表的解析结果（声明侧）。"""

    nodes: List[ParsedNodeDeclaration]
    problems: List[str]
    declared_total_seconds: Optional[float] = None

    @property
    def shots(self) -> List[ParsedShotDeclaration]:
        return [shot for node in self.nodes for shot in node.shots]

    def to_dict(self) -> Dict[str, object]:
        return {"nodes": [node.to_dict() for node in self.nodes],
                "problems": list(self.problems),
                "declared_total_seconds": self.declared_total_seconds}


def looks_like_shot_list(text: str) -> bool:
    """是否是分镜表：至少两个 ``镜号：`` 行，或者一个节点标题加一个镜号。"""
    if not text:
        return False
    numbers = sum(1 for line in text.splitlines()
                  if SHOT_HEADER_RE.match(line))
    if numbers >= 2:
        return True
    has_node = any(NODE_HEADER_RE.match(line) for line in text.splitlines())
    return bool(numbers >= 1 and has_node)


def _map_shot_type(value: str) -> str:
    text = str(value or "")
    for keyword, shot_type in DISTANCE_TO_SHOT:
        if keyword in text:
            return shot_type
    return ""


def _map_camera_move(value: str) -> str:
    text = str(value or "")
    for keyword, movement in INSTRUCTION_TO_MOVE:
        if keyword in text:
            return movement
    return ""


def _split_role_tokens(value: str) -> List[str]:
    """按**顶层**分隔符切「角色」字段：括注里的逗号不算分隔符。

    v1.5 实测踩到的形状：``角色：米迦尔（尾巴在身后保持轻摆状态，尾尖毛簇微翘）``
    ——用 ``re.split(r"[、,，;；/\\s]+")`` 会把括注里的那个逗号当成角色分隔符，
    切出两个都不像名字的碎片，于是这一镜的声明角色**整条丢掉**（同为真实剧本，
    这不是"少认一个"，是"多认出一个"的反面）。
    """
    tokens: List[str] = []
    current: List[str] = []
    depth = 0
    for char in str(value or ""):
        if char in "（(":
            depth += 1
            current.append(char)
            continue
        if char in "）)":
            depth = max(0, depth - 1)
            current.append(char)
            continue
        if depth == 0 and char in "、,，;；/\t ":
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def _plausible_role_names(value: str) -> List[str]:
    """把「角色」字段拆成**候选角色名**：去掉括注、去掉背景群众、去掉编号。

    只做"剔掉明显不是人的写法"，不替剧本猜人：`无角色出场；背景中路人1（渔贩…）`
    得到空表，`米迦尔；背景中路人1（渔贩…）` 得到 `["米迦尔"]`，
    `莉莉安娜、伊恩` 得到两个。
    """
    text = re.sub(r"[（(][^）)]*[）)]", " ", str(value or ""))
    names: List[str] = []
    for token in re.split(r"[、,，;；/\s]+", text):
        name = token.strip()
        if not name or len(name) > 8:
            continue
        if any(marker in name for marker in _ROLE_BACKGROUND_MARKERS):
            continue
        if any(ch.isdigit() for ch in name):
            continue
        if name not in names:
            names.append(name)
    return names


def _speaker_from_roles(value: str) -> str:
    """``台词：`` 行没写说话人时，取「角色」字段的第一位候选。"""
    names = _plausible_role_names(value)
    return names[0] if names else ""


def _split_characters(value: str, known: List[str]) -> List[str]:
    """从"角色："字段里挑出**已知的说话人**。

    只认已经在对白里出现过的名字。这样"背景有大量路人（约30人）在市场
    行走、交易"不会凭空造出一个叫"背景有大量路人"的角色——v1.2 的教训是
    "不要替剧本猜"。

    v1.4 D-3：``莉莉安娜（贵妇）`` 这类**带括注**的写法要把括注当别名，
    取括注之前的部分当正式名——旧实现整段比对，于是同一个人因为写法不同
    变成了两个（或零个）角色。
    """
    if not value:
        return []
    found: List[str] = []
    for token in _split_role_tokens(value):
        name = split_alias(token)[0]
        if not name or len(name) > 8:
            continue
        for candidate in known:
            if name == candidate and name not in found:
                found.append(name)
    return found


def split_alias(token: str) -> Tuple[str, str]:
    """把 ``莉莉安娜（贵妇）`` 拆成 ``("莉莉安娜", "贵妇")``。

    没有括注时别名是空串。只剥**一层**括注，且不猜任何东西：括注里写了
    什么就是什么（v1.4 D-3 / §2.5）。
    """
    text = str(token or "").strip()
    match = re.match(r"^(?P<name>[^（(]+)[（(](?P<alias>[^）)]*)[）)]\s*$", text)
    if match is None:
        return text.strip("（）()"), ""
    return (str(match.group("name")).strip(),
            str(match.group("alias")).strip())


def _aliases_in(value: str, known: List[str]) -> Dict[str, List[str]]:
    """从"角色："字段里收集 ``{正式名: [别名, ...]}``（只认已知说话人）。"""
    mapping: Dict[str, List[str]] = {}
    for token in _split_role_tokens(str(value or "")):
        name, alias = split_alias(token)
        if not name or name not in known or not alias:
            continue
        bucket = mapping.setdefault(name, [])
        if alias not in bucket:
            bucket.append(alias)
    return mapping


def parse_shot_list(text: str, *, title: str = "",
                    tolerance_seconds: float = 0.2
                    ) -> Tuple[ParsedScript, ShotList]:
    """把分镜表解析成 ``(ParsedScript, ShotList)``。

    ``ParsedScript`` 供既有的 Layer 1 下游（对白计时、规划提示）使用；
    ``ShotList`` 是声明侧的严格结构化结果。
    """
    lines = [line.rstrip("\r") for line in (text or "").split("\n")]
    script = ParsedScript(title=title, source_format="shotlist")
    problems: List[str] = []

    known_speakers = _collect_speakers(lines)

    nodes: List[ParsedNodeDeclaration] = []
    node: Optional[ParsedNodeDeclaration] = None
    scene: Optional[ParsedScene] = None
    shot: Optional[ParsedShotDeclaration] = None
    dialogue_lines: List[Tuple[int, str]] = []
    source_index = 0

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue

        node_match = NODE_HEADER_RE.match(stripped)
        if node_match:
            rest = str(node_match.group("rest") or "").strip()
            # 去掉"（总时长：5秒，字数：198）"／"（12s）"这类后缀，只留节点标题；
            # ``**节点1：风起·定场与出场**（12s）`` 的收尾 ``**`` 也一并去掉。
            title_text = re.split(r"[（(]", rest)[0].strip() or rest
            title_text = title_text.strip("*").strip()
            node = ParsedNodeDeclaration(
                node_number=int(node_match.group("num")),
                title=title_text)
            total = NODE_TOTAL_RE.search(stripped)
            if total:
                node.declared_seconds = float(total.group("sec"))
            nodes.append(node)
            shot = None
            scene = ParsedScene(
                scene_number=len(script.scenes) + 1,
                heading=node.title or f"节点{node.node_number}")
            script.scenes.append(scene)
            continue

        shot_match = SHOT_HEADER_RE.match(stripped)
        if shot_match:
            if node is None:                 # 没有节点标题也能解析
                node = ParsedNodeDeclaration(node_number=len(nodes) + 1,
                                             title="")
                nodes.append(node)
            shot = ParsedShotDeclaration(
                shot_number=int(shot_match.group("num")),
                node_number=node.node_number, node_title=node.title)
            node.shots.append(shot)
            continue

        # ``台词："…"（2.75s）``：说话人写在**同镜的「角色」字段**里
        # （v10 电影级分镜的写法）。这一支必须排在 DIALOGUE_RE **前面**：
        # 后者会把行首那两个字当成一个叫"台词"的说话人。归属规则只有一条
        # ——按剧本自己写的角色走；候选多于一个时取第一位，并把这件事
        # **显式记成一条告警**，不静默。
        quoted_match = QUOTED_LINE_RE.match(stripped)
        if quoted_match is not None:
            if shot is not None:
                value = str(quoted_match.group("text") or "").strip()
                roles = _plausible_role_names(shot.fields.get("角色", ""))
                name = roles[0] if roles else ""
                _, declared = extract_declared_seconds(
                    str(quoted_match.group("tail") or "").strip())
                if not name:
                    problems.append(
                        f"镜号 {shot.shot_number} 的台词行没写说话人，"
                        f"而「角色」字段（{shot.fields.get('角色', '')}）里"
                        f"认不出执话人：已按无说话人处理，请核对剧本")
                elif value:
                    if len(roles) > 1:
                        problems.append(
                            f"镜号 {shot.shot_number} 的台词行没写说话人，"
                            f"按「角色」字段第一位归属到「{name}」"
                            f"（同镜候选：{'、'.join(roles)}）")
                    source_index += 1
                    dialogue = ParsedDialogue(
                        character=name, text=value, parenthetical="",
                        source_index=source_index, emotion="normal",
                        declared_seconds=declared)
                    dialogue_lines.append((len(script.scenes), name))
                    if scene is None:
                        scene = ParsedScene(scene_number=1,
                                            heading="（未标注节点）")
                        script.scenes.append(scene)
                    scene.dialogues.append(dialogue)
                    shot.dialogues.append(dialogue)
                    if name not in known_speakers:
                        # 说话人这一遍才认出来，「角色」字段此前是按"已知说话人"
                        # 过滤的——补上之后要**重算这一镜的角色表**，否则
                        # 「角色：米迦尔」会因为"米迦尔还没说过话"被整条丢掉。
                        known_speakers.append(name)
                        shot.characters = _split_characters(
                            shot.fields.get("角色", ""), known_speakers)
            continue

        dialogue_match = DIALOGUE_RE.match(stripped)
        if dialogue_match:
            name = str(dialogue_match.group("speaker") or "").strip()
            text_value = str(dialogue_match.group("text") or "").strip()
            emotion = str(dialogue_match.group("emotion") or "").strip()
            tail = str(dialogue_match.group("tail") or "")
            _, declared = extract_declared_seconds(tail.strip())
            if declared is None:
                cleaned, declared = extract_declared_seconds(stripped)
                if cleaned != stripped:
                    text_value = str(dialogue_match.group("text") or "").strip()
            source_index += 1
            dialogue = ParsedDialogue(
                character=name, text=text_value,
                parenthetical=emotion, source_index=source_index,
                emotion="normal", declared_seconds=declared)
            dialogue_lines.append((len(script.scenes), name))
            if scene is None:
                scene = ParsedScene(scene_number=1, heading="（未标注节点）")
                script.scenes.append(scene)
            scene.dialogues.append(dialogue)
            if shot is not None:
                shot.dialogues.append(dialogue)
            continue

        field_match = FIELD_RE.match(stripped)
        if field_match:
            key = field_match.group("key")
            value = field_match.group("value").strip()
            if shot is None:
                continue
            shot.fields[key] = value
            if key == "预估时长":
                seconds = SECONDS_RE.search(value)
                if seconds:
                    shot.declared_seconds = float(seconds.group("sec"))
            elif key == "拍摄距离":
                shot.shot_type = _map_shot_type(value)
            elif key == "拍摄手法":
                shot.camera_move = _map_camera_move(value)
            elif key == "地点" and scene is not None:
                scene.location = value
            elif key == "时间" and scene is not None:
                scene.time_of_day = value
            elif key == "角色":
                shot.characters = _split_characters(value, known_speakers)
                for canonical, aliases in _aliases_in(value,
                                                      known_speakers).items():
                    bucket = script.character_aliases.setdefault(canonical, [])
                    for alias in aliases:
                        if alias not in bucket:
                            bucket.append(alias)
            # v1.4 D-1：字段值里夹着的台词同样要收——否则它会连同整行
            # 一起被"字段"吃掉，模型永远看不到这句台词。
            for match in INLINE_DIALOGUE_RE.finditer(value):
                name = str(match.group("speaker") or "").strip()
                text_value = str(match.group("text") or "").strip()
                if not (name and text_value):
                    continue
                emotion = str(match.group("emotion") or "").strip()
                # 传给 ``extract_declared_seconds`` 的必须**不是**纯时长串
                # （它要求声明跟在别的文字之后），所以从引号结束处切到匹配末尾。
                tail_text = match.string[match.end("text"):match.end()]
                _, declared = extract_declared_seconds(tail_text.strip())
                source_index += 1
                dialogue = ParsedDialogue(
                    character=name, text=text_value, parenthetical=emotion,
                    source_index=source_index, emotion="normal",
                    declared_seconds=declared)
                dialogue_lines.append((len(script.scenes), name))
                if scene is None:
                    scene = ParsedScene(scene_number=1, heading="（未标注节点）")
                    script.scenes.append(scene)
                scene.dialogues.append(dialogue)
                if shot is not None:
                    shot.dialogues.append(dialogue)
            continue

        if SUMMARY_RE.match(stripped):
            continue

        # 其余非空行当动作描述（画面内容里的分段在后面统一处理）
        if shot is None or scene is None:
            continue
        source_index += 1
        scene.actions.append(ParsedAction(text=stripped,
                                          source_index=source_index))

    _derive_declarations(script, nodes, tolerance_seconds, problems)

    total = [shot.declared_seconds for shot in
             (item for node in nodes for item in node.shots)
             if shot.declared_seconds is not None]
    script.warnings.extend(problems)
    return script, ShotList(nodes=nodes, problems=problems,
                           declared_total_seconds=(round(sum(total), 3)
                                                   if total else None))


def render_declared_shots(script, *, fps: int = 24,
                          max_shots: int = 0, only=None,
                          note: str = "") -> str:
    """把分镜表的逐镜声明渲染成规划提示里的一段（**硬约束**）。

    这是 R015「声明一致性」在提示侧的对应物：先告诉模型约束是什么，
    再由审计核对它有没有照做。v1.2 没有任何一段提示承载这些声明，
    模型只能自己重新规划——实测把 6 个镜号压成 2 个、把 33 秒拉成 39.5 秒。

    v1.4 BW-3：``max_shots = 0``（默认）表示**不限**，全部声明都进提示；
    ``> 0`` 时超过上限直接报 ``E_SCRIPT_002``，不再印"（其余 N 个镜号略）"。

    v1.5：``only`` 给一组镜号时**只渲染这一段**，``note`` 插在抬头之后。
    它服务的是"长分镜表分块出计划"（`planner.plan_chunks`）：一段 16–24 个镜号
    的计划输出能稳稳落在任何供应商的输出预算里，而全表 64 镜的输出会撞上限
    （实测：`emit_plan` 参数 ≈16.5 KB，DeepSeek 的输出上限就卡在那里）。
    ``max_shots`` 的上限检查仍按**全表**判——分块不是放宽声明的约束。
    """
    shots = list(getattr(script, "declared_shots", []) or [])
    if not shots:
        return ""
    limit = int(max_shots or 0)
    if limit > 0 and len(shots) > limit:
        raise ValueError(
            f"E_SCRIPT_002：分镜表声明了 {len(shots)} 个镜号，超过 "
            f"orchestration.max_shots={limit} 的上限。把该值设为 0（不限）"
            f"或提高到不小于声明镜数后重跑。")
    lines = [
        "分镜表声明（**硬约束**：镜号的数量与顺序、镜别、时长、出场角色、"
        "台词文本都不许改动；你只补它没写的东西）：",
    ]
    window = shots[:limit] if limit > 0 else shots
    if only is not None:
        wanted = {int(item) for item in only}
        window = [shot for shot in window if int(shot.shot_number) in wanted]
    if note:
        lines.append(note)
    for shot in window:
        parts = [f"镜号{shot.shot_number}"]
        if shot.shot_type:
            parts.append(shot.shot_type)
        if shot.declared_seconds is not None:
            frames = frames_from_seconds(shot.declared_seconds, fps)
            parts.append(f"{shot.declared_seconds:g} 秒（{frames} 帧）")
        if shot.camera_move:
            parts.append(shot.camera_move)
        parts.append("、".join(shot.characters) if shot.characters else "无角色")
        lines.append("- " + "｜".join(parts))
        purpose = shot.field("作用")
        if purpose:
            lines.append(f"  意图：{purpose}")
        for dialogue in shot.dialogues:
            seconds = (f"（约 {dialogue.declared_seconds:g} 秒）"
                       if dialogue.declared_seconds else "")
            lines.append(f"  台词 {dialogue.character}：“{dialogue.text}”{seconds}")
    total = getattr(script, "declared_total_seconds", None)
    if total:
        lines.append(f"合计声明时长：{total:g} 秒"
                     f"（{frames_from_seconds(total, fps)} 帧）"
                     f"，共 {len(shots)} 个镜号")
    return "\n".join(lines)


def _collect_speakers(lines: List[str]) -> List[str]:
    """先扫一遍，收集所有台词说话人——"角色："字段只认这些人。

    v1.5：``台词："…"`` 这种**不带说话人**的写法同样要收——它的说话人由
    同一分镜的「角色」字段给出，所以这里要带着"当前镜的「角色」"一起走。
    """
    names: List[str] = []
    role_field = ""
    for line in lines:
        stripped = line.strip()
        field_match = FIELD_RE.match(stripped)
        if field_match is not None and field_match.group("key") == "角色":
            role_field = field_match.group("value").strip()
        elif SHOT_HEADER_RE.match(stripped) or NODE_HEADER_RE.match(stripped):
            # 换镜/换节点：上一镜的「角色」不再适用
            role_field = ""
        quoted = QUOTED_LINE_RE.match(stripped)
        if quoted is not None:
            name = _speaker_from_roles(role_field)
            if name and name not in names:
                names.append(name)
            continue
        # v1.4 D-1：行内台词（``画面内容：米迦尔："…"``）同样是说话人来源，
        # 否则"角色：米迦尔"会因为米迦尔"没说过话"而被整条丢掉。
        for match in INLINE_DIALOGUE_RE.finditer(stripped):
            name = str(match.group("speaker") or "").strip()
            if name and name not in names:
                names.append(name)
    return names


def _derive_declarations(script: ParsedScript,
                         nodes: List[ParsedNodeDeclaration],
                         tolerance_seconds: float,
                         problems: List[str]) -> None:
    """从字段里派生结构化声明，并做三处自洽校验（只报警，不阻断）。"""
    # 场景标题优先用「地点 - 时间」（这也是 §4.1 的标题惯例），
    # 缺字段时退回节点标题，保证 planner 拿到的 heading 始终可读。
    for index, node in enumerate(nodes):
        if index >= len(script.scenes):
            break
        scene = script.scenes[index]
        shot = node.shots[0] if node.shots else None
        location = shot.field("地点") if shot is not None else ""
        time_of_day = shot.field("时间") if shot is not None else ""
        if location:
            scene.location = location
            scene.time_of_day = time_of_day
            scene.heading = (f"{location} - {time_of_day}" if time_of_day
                             else location)

    for node in nodes:
        for shot in node.shots:
            content = shot.field("画面内容") or shot.field("背景内容")
            shot.timecodes = [(float(match.group("start")),
                               float(match.group("end")))
                              for match in TIMECODE_RE.finditer(content)]
            # 只统计**本镜自己的**台词声明，不能拿全片的对话去摊
            declared = [dialogue.declared_seconds
                        for dialogue in shot.dialogues
                        if dialogue.declared_seconds is not None]
            if declared:
                shot.declared_dialogue_seconds = round(sum(declared), 3)

    for node in nodes:
        for shot in node.shots:
            if shot.declared_seconds is None:
                problems.append(
                    f"镜号 {shot.shot_number} 没有「预估时长」声明，"
                    f"将按语速估算")

        declared = node.declared_shot_seconds
        if node.declared_seconds and declared is not None:
            gap = abs(node.declared_seconds - declared)
            if gap > tolerance_seconds:
                problems.append(
                    f"节点 {node.node_number} 声明总时长 "
                    f"{node.declared_seconds:g} 秒，"
                    f"但各镜声明之和是 {declared:g} 秒（差 {gap:.2f} 秒）")
    script.declared_nodes = nodes
