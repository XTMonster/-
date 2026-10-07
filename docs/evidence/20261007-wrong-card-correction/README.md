# 勘误：`topic_mismatch` 的机械判据**读的是一份残缺的卡索引**——"删 9 条边"的依据不成立

日期 2026-10-07 03:35–03:45。起因：复核 `../20261007-grounding-ruling/README.md` §二那张表
（"判不了的边 9 条；这些边的成员判定 `topic_mismatch 14`／`topic_matches 1`"）时，
发现产出它的探针 `work/_probe_wrong_card.py` **看不到一半的卡库**。

## 一、三处**已实测**的缺陷（都在同一份判据上）

### 1. 手写卡完全不在索引里

`_probe_wrong_card.py::load_cards()` 只读 `knowledge/cards_generated/*.yaml`（用正则切 `\n- ` 块）。
而**手写卡住在 Python 模块里**（`block_director/knowledge/cards_composition.py` 等，
经 `corpus.HANDWRITTEN_CARDS` 暴露，共 **132** 张）⇒ 判定时 `cards.get(id)` 取不到，
于是该来源卡同时得到 `text=""` 与 `topic=""`。

### 2. 手写卡根本没有 `topic` 字段

`Card` 的字段是 `id/domain/title/content/keywords/rules/parameters/examples/related/
engine_support/emotion/tags`——**没有 `topic`**。手写卡有的是 `domain`
（`composition` / `performance` / `cinematography` …）。所以"来源卡的 `topic` 是否等于成员 kind"
这个判据，对手写卡来源的边**天然恒假**。

### 3. `topic` 字段本身有大面积空洞，且粒度比 kind 粗

对 `knowledge/cards_generated/*.jsonl`（**2,221** 张生成卡）逐张统计：

| 量 | 值 |
|---|---|
| 生成卡总数 | 2,221 |
| **`topic` 为空** | **1,172（52.8%）** |
| 不同的 `topic` 取值 | **11**（storyboard 229／shot_language 222／editing 182／anime 141／lighting 104／color 99／camera_angle 59／performance 6／character_design 5／technique 2／空 1172） |

⇒ `topic` 是一枚**粗粒度、过半缺失**的标签，而成员 `kind` 是细粒度槽位名
（`composition_rule` / `headroom_policy` / `camera_angle`）。**"`topic` ≠ 成员 kind" 在这份语料里是常态**，
不能当作"这张卡挂错了"的证据。

## 二、用**权威注册表**重算同一批 15 个槽位

`work/_probe_wrong_card_full.py`（本目录留档 `probe_wrong_card_full.py`，原始输出 `wrong_card_full.json`）：
索引＝`corpus.CARDS` 的合并规则（手写 ＋ 生成，2,221 ＋ 132 张）＋ `hypergraph.nodes.jsonl` 的别名；
正文口径与 `grounding.asserted_text` 逐字一致（标题＋正文＋关键词＋标签，
**刻意不收** `related`——那里放的是**别的卡的 id**，拿它当正文会造出恒真的假命中）；
对手写卡用 `domain` 代替 `topic`；`topic` 为空**单独记成 `topic_unknown`**，不再算 `mismatch`。

| 判定 | 旧探针（YAML-only） | **修正版（权威索引）** |
|---|---|---|
| `in_card_text`（取值就在来源卡正文里） | 0 | **1** |
| 主题相符（`topic`／`domain` 与 kind 对得上） | 1 | **2** |
| `topic_mismatch` | **14** | **6** |
| `topic_unknown`（来源卡的 `topic` **是空的**） | 0 | **6** |
| 合计槽位 | 15 | 15 |

两条**具体的翻案**：

* `hg:d090d7ce0096` 的 `composition_rule:headroom`：来源卡里有**手写卡 `comp_headroom`**
  （`domain=composition`，`title=头顶留白`，`keywords=['头顶留白','headroom','留白']`）
  ⇒ `headroom` **就写在卡里**，判 `in_card_text`。旧探针因为读不到手写卡，把它记成 `topic_mismatch`
  ——**这是要删掉的那批里的一条**。
* `hg:5b8b86de2d87` 的 `composition_rule:lead_room`：来源卡含手写卡 `comp_diagonal` / `comp_eye_trace`
  （`domain=composition`）与生成卡 `gen_cine_0213`（`topic=camera_angle`）⇒ 主题**对得上**。

## 三、`hg:400a2bfcda8e` 那类"多来源"的边，判据本身也不该用 `topic` 定生死

它的 23 张来源卡里 **18 张 `topic` 为空**（其余是 color／shot_language／anime／blocking）。
对所有来源卡取 `topic` 并集，得到的是一堆**互不相同的域标签**——"并集里没有
`composition_rule`"这件事，既不能证明没挂错卡，也不能证明挂对了。

⇒ **该定生死的是来源卡正文**（判据 `attestation.audit()` 拼的正是它），
这正是裁定第 ③ 条那 90 槽位三分类让分类者读的东西。

## 四、结论与处置

1. **"删 9 条边"的机械依据不成立**：15 个槽位里真正有"主题不符"信号的只有 **6** 个，
   **6** 个是"`topic` 字段空着（不知道）"，**3** 个是正命中／主题相符。
   `../20261007-grounding-ruling/README.md` §二那句"这 14 个槽位落在**删边**那一支"**作废**。
2. **本轮依旧一条边不删、索引一个字节不动**（与 `013d516` 同结论，但理由是"判据不成立"，
   而不是"代价太大"）。删边的连带后果（索引换代 ⇒ 23 份运行 `pins.index.fingerprint` 全失配）
   因此**不必付**。
3. 处置仍按裁定：**等 90 槽位三分类**给出真错率，再决定"修数据／接受下界"；
   而"挂错卡"的真判据要**重建在权威索引上**（本目录的探针就是那根新尺子的草稿）。

## 五、复算（逐字可跑）

```
python work/_probe_wrong_card.py            # 旧：YAML-only —— topic_mismatch 14 / topic_matches 1
python work/_probe_wrong_card_full.py       # 新：权威索引 —— mismatch 6 / unknown 6 / 相符 2 / 命中 1
python -c "import json,pathlib;d=pathlib.Path('knowledge/cards_generated');n=e=0;[ (globals().__setitem__('n',n+1),) for _ in []]"   # 见下（topic 空洞率）
```

`topic` 空洞率的复算命令（逐字）：

```
python -c "import json,pathlib;tot=emp=0;
[ (globals().__setitem__('tot',tot+1), globals().__setitem__('emp',emp+1) if not str(json.loads(r).get('topic') or '') else None)
  for p in sorted(pathlib.Path('knowledge/cards_generated').glob('*.jsonl'))
  for r in p.read_text(encoding='utf-8').split('\n') if r.strip() ]
print(tot, emp)"   # → 2221 1172
```

## 六、未验证 / 边界

1. 修正版判据**仍是机械的**：`domain`↔`kind` 的对应是我写的粗粒度启发式
   （`token in kind or kind in token`），没有独立核对。
2. `topic` 字段的**准确率**依然没核（它错，这枚信号就跟着错）——裁定 §四.2 早就留了这句。
3. 本目录**没有**判定任何一条边"该删"或"该留"；它只证明**旧依据不成立**。
4. `hg:3f26bdf8d230`（`headroom_policy:cinematic` ← `cine_height:cinematography`）
   这类**只有一张来源卡、且主题确实不符**的槽位，修正后仍记 `topic_mismatch`
   ——它们是"值得逐条看"的候选，不是"可机械删除"的对象。
