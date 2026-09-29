# ADR-0010 SceneContract：说话人解析不出来时不许伪造 `character_id`

状态：Accepted（v1.4 / P11）

## 背景

v1.3 的角色链路是"分镜表 → 计划"直通。说话人对不上时，驱动器会写一个
**空的** `character_id`，却不记录"原本是谁"；`sdl_validator` 的 S2 只校验
已解析的 id，于是"空 id"看起来永远合法。同一份剧本里"莉莉安娜"与
"莉莉安娜（贵妇）"还会被当成两个人（或零个角色）。

## 决策

新增**纯计算**的语义收敛层 `layer5_orchestrator/scene_contract.py`：

- 逐镜产出 `ShotContract`：`intent` / `characters` / `facing_target` /
  `dialogues[{speaker_raw, speaker, speaker_status}]` / `vfx` / `unresolved[]`；
- 说话人解析**只做精确匹配**（id 全等，或经 `aliases` 映射到 id）。
  解析不出来就 `speaker = ""`、`speaker_status = "unresolved"`，
  并进 `unresolved[]`——**不猜名字**（F2）；
- 驱动器把它用在两处：`_pin_declared_dialogue` 写 `speaker_raw` /
  `speaker_status` 与 `dialogue_pins`，并记一条 `speaker_unresolved` 审计事件。

## 后果

- 未解析的说话人可以被**计数**（而不是被静默吞掉），也能人工裁决；
- 别名的规范化（`莉莉安娜（贵妇）` → canonical ＋ alias）有了单一落点；
- **被否决的替代方案**：给未解析的说话人写一个"猜出来的"角色 id——
  它会让 S2 判成坏数据，或者更糟：把台词安到错误的人身上。
