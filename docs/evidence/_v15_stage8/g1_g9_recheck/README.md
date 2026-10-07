# P8-T8：G1–G9 历史点名逐条核查（**只核不改**）

**run-id**：`_v15_stage8/g1_g9_recheck`
**卡**：`执行文档v1.5/dispatch_graph.json` 的 `P8-T8` —— 出处
`TECH_SOLUTIONS.md` §六（"G1…G9 逐条核查『历史点名但现行台账未见收口』；
若属实只出提案（涉判据/换代的一律标『须裁决』），**一处代码都不改**"）。
**HEAD**：`f6530c6e44702028c6e42a9e1d11436c0b19d1c2`（工作树未提交）
**纪律**：R-5（判据/阈值/门限一个字未动）、R-8（索引/夹具一个字节未动）。
本卡**只读**：没有改任何代码、索引、夹具、判据。

---

## 1. 结论（先给答案）

**10 条里 4 条已收口、6 条仍未收口。** 未收口的 6 条**全部**是要么触换代
（改提示／改索引／改夹具），要么要用户拍口径——按卡的纪律，全部**只出提案**：

> **本卡的第一版仪器把 G5 判错了，已当场改正并留痕**（初版按
> `ACCEPTANCE_STATUS.md:1940-1942` 的"还没做"抄了**文件名代理**，去查
> `work/hypergraph.chunk*.jsonl`；实测对拍发现该条**早已收口**于
> `:2168-2180` §29.4 的**原子边缓存**）。改的是**仪器**，判据一字未动；
> 逐条见 §3 的 G5。

| # | 条目 | 判决 | 一句话 |
|---|---|---|---|
| **G1** | 抽取提示历史措辞（"13 类"、4b 的 `EMOTION_PACK` 宿主） | **未收口** | 仍是 `extract/v18`，三处措辞原样在；改它＝覆盖率交换（已实测否决） |
| **G2** | 运镜政策无宿主（`gen_cine_0247` 的禁半） | **未收口** | 卡本身已进索引（1 条边），但**禁半**仍无处安放——没有**专用**边型/kind，现行宿主只是 `INTENT_PACK` 的 `movement` 槽位；且那条边写的是 `movement=固定`（与卡义相反） |
| **G3** | ollama 残片 | **未处置** | 工作区外 18.25 GiB 仍在（仍被 tag 引用）；工作区内 `work/` 另有 **49.39 GiB** 三份 bin |
| **G4** | 抽取提示漂移（§22.2） | **未收口** | 与 G1 同源；必须"改提示＋整库重抽＋重标 oracle"同批 |
| **G5** | 抽取结果缓存（"命中就不重抽"） | **已收口** | `tools/kb_fetch/atom_cache.py` 早已落地并被接线（§29.4）；钥匙＝渲染后的提示＋模型＋温度＋解码＋卡文，`chunks[]` 708 条 per-chunk 账，守门用例在。残留：缓存落 `work/`（不入库、不进指纹） |
| **G6** | `rule_of_thirds`/`lead_room` 口径；求解器 vs 评分模型 | **未收口** | 没有**成文**裁决；机制已落地（§68/§69 的横移＋竖直抬升、v1.5 P3-T4 声明式消费），**阈值一字未动** |
| **G7** | `drift_is_bridged` 的参照系 | **已收口** | 换成"赦免额对得上欠账额"，`tests/test_axis_crossing_events.py:158-173` 钉住 |
| **G8** | Q5 基准串口径 | **未拍板** | 链上已按硬规则 2 选 audit 通道（`emitted` 为 join 键），口径本身仍未裁 |
| **G9** | 别名表不进缓存键 | **已收口** | §21（P14-12）补第八格 `vocabulary_fingerprint`，发货 manifest 也是 8 格 |
| **E2** | 悬空引用 `OPEN_PROBLEMS (19)/⑲` | **已收口** | 随 P1-T1 落地；`AGENTS.md` 已无该引用，台账 :1331 改指 `OPEN_ITEMS_20261007.md` B1 |

机器可读版：`verdicts.json`（每条 `{id, verdict, evidence[], proposal, requires_adjudication}`）。

---

## 2. 复算入口（本卡的"有效测试"）

本卡不改代码，所以**没有 pytest 用例**；取而代之的是一支**离线、确定性、只读**
的复算仪器，把上表里所有机械可判的部分钉住：

```powershell
python docs/evidence/_v15_stage8/g1_g9_recheck/verify_recheck.py --check
-> [OK] G1 … [OK] E2  （10 条全部与记录一致）        exit 0

python docs/evidence/_v15_stage8/g1_g9_recheck/verify_recheck.py --check `
    --json docs/evidence/_v15_stage8/g1_g9_recheck/verify_recheck.json
-> 逐条 {ok[], mismatch[]} 落盘（本次：10 条 / mismatch 全空）
```

它的语义是**"我记录的现状还在不在"**，不是判据：一旦有人真的把某条做掉
（例如把提示里的"13 类"改成 16 类、或新增了运镜政策宿主），脚本会**红**并
要求更新本目录的两份产物——这是防"文档漂移"的守卫（这一轮清单 §四 E1–E5 就是
同一类缺陷）。它**不写**任何仓库产物（只在你显式给 `--json` 时写你指定的路径）。

本次实测输出（节选，逐字）：

```
[OK] G1 抽取提示历史措辞（13 类 / 4b EMOTION_PACK 宿主）
    ok   PROMPT_VERSION = "extract/v18"
    ok   开场/规则 1 仍写 13 类
    ok   规则 4b 仍写挂到 EMOTION_PACK
[OK] G2 运镜政策无宿主 / gen_cine_0247 禁半
    ok   引用 gen_cine_0247 的边 = 1 条（卡已进索引）
    ok   这 1 条边**没有** forbid 成员 ⇒ 卡里『避免长时间静止固定』的禁半仍未进索引
    ok   EDGE_TYPES/QUALIFIER_KINDS 里仍没有『运镜政策』宿主
[OK] G3 ollama 残片（工作区外 blob + 工作区内 bin）
    ok   work/ollama_leftover_*.bin = 3 份 / 合计 49.39 GiB
    ok   C:\Users\小皮\.ollama\models\blobs\sha256-0373edb0… 仍在（18.25 GiB）
[OK] G5 抽取结果缓存（"命中就不重抽"）
    ok   tools/kb_fetch/atom_cache.py 在（第 1 段抽取结果的缓存／断点续跑）
    ok   build_hypergraph 真的接上了它（`import atom_cache` ＋ `--no-atom-cache` 可关）
    ok   发货 manifest 记 atom_cache.enabled=true、path=work/hypergraph.atom_cache.jsonl
    ok   chunks[] 带 per-chunk 账（708 条，每条含 sha256/status/edges）
    ok   守门用例在（tests/test_hypergraph_atom_cache.py：键只随输入动）
    ok   粒度＝抽取单元，不是 §28.1 设想的 hypergraph.chunk*.jsonl；判据相同
[OK] G6 构图口径（rule_of_thirds / lead_room）
    ok   PASS_SCORE 仍是 70.0（没有被拿去将就口径）
    ok   docs/adr 里仍**没有**这两条口径的裁决（口径仍未收口）
[OK] G7 drift_is_bridged 的参照系
    ok   drift_is_bridged：53° 漂移只交代了 6° ⇒ 不赦免
    ok   drift_is_bridged：100° 可见慢漂移 ⇒ 赦免
[OK] G9 别名表进缓存键
    ok   CACHE_KEY_FIELDS = 8 格，含 vocabulary_fingerprint
10 条全部与 P8-T8 的记录一致。
```

---

## 3. 逐条证据（文件:行号 / 命令 / 真实输出）

### G1 / G4 —— 抽取提示的历史措辞未随 `extract/v18` 收口

```powershell
rg -n "PROMPT_VERSION|只能取下面|只有这 13 个|把下面 13 类|挂在 EMOTION_PACK 上" tools/kb_fetch/build_hypergraph.py
```

| 位置 | 原文 |
|---|---|
| `tools/kb_fetch/build_hypergraph.py:182` | `PROMPT_VERSION = "extract/v18"` |
| `:402` | `1. \`type\` 只能取下面 **13 类**之一，必填成员必须写全` |
| `:436` | `1b. **只有这 13 个 \`type\` 字符串**` |
| `:479` | `**把下面 13 类逐条问一遍**，命中就写一条（每卡上限 4 条）` |
| `:459-462` | `4b. …（挂在 \`EMOTION_PACK\` 上；如果这张卡本身不是情绪卡，就把它写成"该情绪下不要这样拍"的 \`EMOTION_PACK\`）` |

**为什么没修（这不是"忘了"而是实测否决）**——`build_hypergraph.py:125-143` 记着
三个变体的同批对照（同语料、同模型、只改提示文本）：

| 提示文本 | 原子边 | 有边可标注的卡 | §4.1b 分母下界（≥95%） |
|---|---|---|---|
| 原文（已入库） | 2846 | **2099 / 2130 = 98.5%** | 过 |
| 只改计数 ＋ 补 6b 三行 | 2528 | 1786 = 83.9% | **红** |
| 再把 4b 改成"没有落地主体就别写这条边" | 2160 | 1688 = 79.2% | **红** |
| 4b 加一句"这条不等于少写边" | 2213 | 1734 = 81.4% | **红** |

⇒ 结论原文（`:137-143`）：**"v12 的覆盖率有一部分正是那两处『漂移』挣来的"**，
真正的根因修复必须 **改提示 ＋ 整库重抽 ＋ 整份 oracle 重标同批落地**。
发货代仍是 `extract/v18`（`knowledge/hypergraph.manifest.json`），所以 G4 与 G1
**是同一条工作项**。

**提案（⚖️ 须裁决，涉换代与 oracle 判分输入）**：不单独做文本修复；把它并进
下一次换代，并把"覆盖率 + 精度"一起当验收指标看（现有兜底＝归并期精确度门
`unsupported_prohibition_hosts`，`build_hypergraph.py` 的 `merge` 账里有它的读数）。

### G2 —— 运镜政策仍没有"诚实宿主"

```powershell
python -c "import json,pathlib; [print(json.loads(l)['edge_id'], json.loads(l)['type'], json.loads(l)['members']) for l in pathlib.Path('knowledge/hypergraph.edges.jsonl').read_text(encoding='utf-8').splitlines() if 'gen_cine_0247' in (json.loads(l).get('sources') or [])]"
-> hg:f6fd8f040745 INTENT_PACK [['allow','intent','intent:留白'], ['allow','shot_size','shot_size:LS'], ['qualifier','movement','movement:固定']]
```

* 引用 `gen_cine_0247` 的边 **只有 1 条**，而且**没有任何 `forbid` 成员**——
  卡里那句"**避免长时间静止固定**"（禁半）依旧进不了索引。
* 那条边写的是 `movement=固定`，与卡义**相反**（这正是三分类抽查里被判
  `topic_mismatch` / `wrong_card` 的形态之一）。
* `knowledge/card_scope.json:1100` 显示它现在**在** catalogue（**不在**
  `excluded`）——即"孤儿卡"那条老问题已归零，**剩下的只是禁半没有宿主**。
* `AGENTS.md:910` 仍写着这一条，措辞与实测一致（**这条不是文档漂移**）。
* **"无宿主"的作用域要说清**：它只在"没有**专用**边型/kind"这一层成立——
  `EDGE_TYPES` 里没有 `MOVEMENT_POLICY`、`QUALIFIER_KINDS` 里没有 `movement_policy`；
  而 `forbid` 在 v1.8 之后**可以**挂在任何"本类型里本来就有这个槽位"的边上，
  所以现行那 1 条边**能**承载 `movement` 的 allow/qualifier，只是卡里那条**禁令**
  从来没被写进去（实测：该边 0 个 `forbid` 成员）。

**提案（⚖️ 须裁决）**：给 schema 一个能诚实承载"运镜政策/禁区"的宿主——
路线 A：`SHOT_PATTERN` 增可选 `(forbid, movement)` 语义；路线 B：新增
`MOVEMENT_POLICY` 型。两者都要跟着一次**整库重抽**（门④ 要求每类 ≥30 对
≥10 卡），所以与 G1/G4 **同批落地**才有意义。

### G3 —— ollama 残片（用户手工项）

```powershell
Get-ChildItem "$env:USERPROFILE\.ollama\models\blobs" | Sort-Object Length -Descending | Select-Object -First 3 Name,@{n='GiB';e={[math]::Round($_.Length/1GB,2)}}
-> sha256-0373edb066522ad4e8d022fe9ee6dcf02a853cf9477ebee6bfebc3e55e6929c0   18.25
Get-ChildItem work -Filter "ollama*" | Select-Object Name,@{n='GiB';e={[math]::Round($_.Length/1GB,2)}}
-> ollama_leftover_266540326.bin 12.65 / ollama_leftover_b1da6f96.bin 18.25 / ollama_leftover_qwen25_32b.bin 18.49
```

* **旧读数要更新**：`ACCEPTANCE_STATUS.md:1475-1478` 记的是"17.69 GB 续传残件 ＋
  18.25 GB 坏修订 ≈ 36 GB，另 `work/` ≈53 GB"。今天实测：工作区外那枚
  **17.69 GiB 的 `-partial` 已不在**（该目录合计只剩 18.25 GiB）；工作区内
  `work/ollama_leftover_*.bin` 是 **3 份 / 49.39 GiB**。
* 工作区外那枚仍被 `qwen3-vl:30b` 的 tag 引用，**删它等于卸载该模型**（用户已授权）。

**提案（⚖️ 须裁决）**：① 工作区外那枚按 `ACCEPTANCE_STATUS.md` §9.6 的命令由
用户手工删；② `work/` 下三份 bin 在工作区内、技术可删，但属**破坏性操作**，
等用户点头再动（本卡不动）。

### G5 —— 已收口（抽取结果缓存"命中就不重抽"）**——本卡的第一版判错了，这里留痕**

**第一版错在哪（仪器错，不是判据错）**：初版照
`docs/knowledge/ACCEPTANCE_STATUS.md:1940-1942`（§28.1 的"还没做"）写成
"只有按卡的复用、`work/` 下不存在 `hypergraph.chunk*.jsonl`"——那是拿**文件名**
当代理去看"机制在不在"。机制的名字不叫 `hypergraph.chunk*.jsonl`，
所以代理找错了地方。逐条对拍后改为**钉住机制本身**：

```powershell
Get-ChildItem tools/kb_fetch/atom_cache.py,tests/test_hypergraph_atom_cache.py
-> atom_cache.py 12,169 B (2026-10-02 20:34) / test_hypergraph_atom_cache.py 17,186 B
rg -n "atom_cache|no-atom-cache" tools/kb_fetch/build_hypergraph.py
-> :45/:51 import atom_cache   :73 ATOM_CACHE = common.WORK / "hypergraph.atom_cache.jsonl"
   :1642 atom_cache.chunk_ledger(...)   :1778 cache = atom_cache.AtomCache(ATOM_CACHE, "", enabled=cache_enabled)
   :2084 --no-atom-cache   :2132/2149/2154 cache_enabled=not args.no_atom_cache
python -c "import json,pathlib;d=json.loads(pathlib.Path('knowledge/hypergraph.manifest.json').read_text(encoding='utf-8'));print(d['atom_cache'], len(d['chunks']), d['chunks'][0])"
-> {'path': 'work/hypergraph.atom_cache.jsonl', 'enabled': True} 708
   {'chunk_id': '08e30130958be2b4…_MIT21L_011F13_l#000', 'sha256': '69bd8772…', 'status': 'done', 'edges': [...]}
Get-ChildItem work\hypergraph.atom_cache.jsonl -> 8,597,755 B (2026-10-03 01:48)
```

台账自己早就记了收口（`ACCEPTANCE_STATUS.md:2168-2180`，§29.4）：

> §28.1 记的"全量重建仍会重抽、两次构建不同字节"，在**原子边缓存**
> （`tools/kb_fetch/atom_cache.py`，键 = 渲染后的整段提示 ＋ 模型 ＋ 温度 ＋ 解码 ＋
> prompt 版本，指纹不匹配则整份作废）落地之后实测收敛：
> `run4 2f86f6ca…` 与 `run5 2f86f6ca…` **逐字节一致**，缓存条目不再增长。

⇒ **G5 结案**，但**残留照样写清**（不设门）：

1. 缓存文件落 `work/`（`/work/` 已 gitignore）⇒ **不入库、不进指纹**；
   干净检出上的全量重建仍会真调模型 ⇒ "逐字节一致"是**有缓存前提**的机制；
2. 粒度是**抽取单元**（一张卡的渲染后提示等等），不是"任意 chunk"；
   与 §28.1 原话的**命名**不同、**判据**（命中就不重抽）相同；
3. `ACCEPTANCE_STATUS.md:1940-1942` 那两句仍是旧表述 ⇒ **建议加一条指向
   `:2168` §29.4 的编者注**（属文档一致性，不是判据）。

### G6 —— 构图口径仍未裁（两处）

```powershell
rg -n "PASS_SCORE|lead_room|rule_of_thirds" block_director/cinema/composition.py
-> :19 "lead_room": 0.20   :20 "rule_of_thirds": 0.15   :26 PASS_SCORE = 70.0
rg -ln "rule_of_thirds|lead_room" docs/adr     -> （无输出：没有裁决文书）
```

两条口径（`rule_of_thirds` / `lead_room` 怎么算；**求解器遵守 §10.4 vs 评分模型
接受居中主体**）到今天仍**没有裁决文书**。仓库里已有两条**实测约束**：

* `ACCEPTANCE_STATUS.md:4091` §61.1 —— **负结果**："让求解器遵守 §10.4 不能直接开"；
* `ACCEPTANCE_STATUS.md:4409` —— 经测量的那一步（视线留白横移）**决定接上**，
  并在 §六十八/§六十九 合计 +14 / +13 个构图门镜头；
* v1.5 的 P3-T4 落的是**声明式消费**（`shot.composition` 有声明才偏置，
  空声明＝零行为差），它**没有**回答"默认该守哪一条"。

**提案（⚖️ 须裁决）**：出三条路的裁决包（A 求解器遵守 §10.4；B 评分模型接受
居中主体；C 维持现状＝声明式消费 ＋ 空声明零差）。红线：**不许靠调 `PASS_SCORE`**
（`cinema/composition.py:26`）解决。

### G7 —— 已收口（drift_is_bridged 的参照系换了）

```powershell
rg -n -A 18 "^def drift_is_bridged" block_director/cinema/axis.py
-> :321 def drift_is_bridged(angle_deg, visible_deg, neutral) -> bool
   正确形状是"**赦免额对得上欠账额**"：阈值内（≤ AXIS_DRIFT_DEG）免费，
   超出部分要由**看得见的旋转累计**偿付；中性机位直接算交代。
   实现：if neutral: return True; return visible_deg >= max(0.0, angle_deg - AXIS_DRIFT_DEG)
```

旧的"历史上**有过一次**看得见且转过 ≥5° 就赦免"是**存在性判定**（会放过
"一次 6° 换位洗白 53° 暗重建"）。现在这条被 `tests/test_axis_crossing_events.py:158-173`
钉住（53°/6° 不赦免、100°/100° 赦免、阈值内免费、中性机位赦免），生产侧调用点
`layer3_engine/rule_checker.py:360`。⇒ **G7 结案**。

### G8 —— Q5 的基准串口径仍未拍板，但链上已选 audit 通道

```powershell
rg -n "emitted|retrieval_call" tools/knowledge/quality.py
-> :354 `emitted`（**join 键**）＝ `audit_log.jsonl` 的 `retrieval_call.data.query`
-> :226-231 / :400-407 重推串降级为 drift 诊断
```

`AGENTS.md:912-920` 仍记着"**仍未拍板**"，并附那次真实运行的实测：计划期发出的
串与 build 后重推的串 **6/6 镜都不同**（`镜头` 由取景求解器后补、`运镜` 由工具
调用后补，而逐镜检索发生在 editor 调用之前）。硬规则 2 只允许读 audit 的逐次事件，
所以 join 键改用 `emitted`、重推串降级为 `drift` 诊断。

**提案（⚖️ 须裁决）**：口径本身属"入口形状"——条目该不该点名被量的字段、
计划要不要在**检索前**就带上焦段与运镜。**不动 oracle、不动判据、不重标**。

### G9 —— 已收口（别名表进缓存键第八格）

```powershell
python -c "from tools.kb_fetch.build_hypergraph import CACHE_KEY_FIELDS as c; print(len(c), c)"
-> 8 ('corpus_sha256','model','prompt_version','chunker_version','decode','schema_version','validation_rules_version','vocabulary_fingerprint')
```

§21（P14-12）把 `vocabulary_fingerprint` 补成**第八个分量**，而且它是"**从代码
现算**"的（改别名表 ⇒ 当场换指纹，`build_hypergraph.py:323-346`）。发货
`knowledge/hypergraph.manifest.json` 的 `cache_key` 也是 8 键齐
（`vocabulary_fingerprint=f72697ec…`）。⇒ **G9 结案**（B4 的"编别名"仍是另一件事，
它要的是别名内容本身，与本条无关）。

### E2 —— 顺手钉住的悬空引用（P1-T1 的验收项）

```powershell
rg -n "OPEN_PROBLEMS" AGENTS.md                 -> （无输出）
rg -n "OPEN_ITEMS_20261007" docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md
-> :1331 `docs/knowledge/OPEN_ITEMS_20261007.md` B1）"并附**可复核来源**。
```

---

## 4. 缺口与风险（明确标"未验证"）

1. **未验证：G3 的"工作区外"是只读了 3 个采样点**——`~/.ollama/models/blobs`
   只按大小排序看了前几项 + 目录合计；没有逐个 blob 判定"是残件还是活模型"。
2. **未验证：G2 的边是不是"该说的话"**——本卡只做机械核查（有没有 forbid 成员、
   有没有宿主边型）；"`movement=固定` 与卡义相反"是**引用台账与抽查样本**的判断，
   不是本卡新做的语义裁决（语义裁决在三分类那条线，见 `20261007-grounding-sample90/`）。
3. **未验证：G4 的"整库重抽"成本**——只知道它必须与重标同批，没有估过 token/墙钟
   （那是换代卡的活）。
4. **无法验证：GLM 通道**——本机 `GLM_API_KEY` 未设置（实测 `False`），
   凡需 GLM 交叉对拍的条目（G1/G4 的复核、C1 剩余 10 批）本卡**没跑**，如实记账。
5. **风险：本卡的 `--check` 是"状态断言"**——它是防文档漂移用的，**不是判据**；
   若有人合规地把某条做掉，脚本会红，正确动作是**更新 `verdicts.json` / 本文件**，
   而不是把断言删掉。
6. **如实记一次仪器返工**：G5 的第一版判词（"未收口"）是**错的**，根因是
   "拿文件名当机制代理"（去查 `work/hypergraph.chunk*.jsonl`）。已改为钉住机制
   （模块在 ∧ 接线在 ∧ manifest 记 ∧ per-chunk 账在 ∧ 守门用例在），并留下这段
   痕迹。**判据/阈值/门限全程一字未动**；改的只是这支复算仪器。
7. **未验证：G5 的"两次构建逐字节一致"没有本卡复跑**——它是 §29.4 的实测读数
   （run4 ≡ run5），本卡只核实了**机制在**与**账在**；要复现需一次全量重建
   （数小时 + 真调模型），本卡刻意没跑。

## 5. 建议动作（可执行到文件与行）

| 优先级 | 动作 | 落在哪 |
|---|---|---|
| 高 | 把 G1/G4/G2 合成**一个换代工作项**（改提示 ＋ 加运镜政策宿主 ＋ 整库重抽 ＋ 重标 oracle），先出成本与影响面估算（G5 的缓存已就位，是这次换代的**加速器**：重抽时命中则省调用） | 新 `docs/knowledge/REGEN_LOG_TEMPLATE.md` 的登记表 ＋ `dispatch_graph.json` 新卡 |
| 高 | G6 的三条路口径包（A/B/C）交用户裁决；**不许**动 `PASS_SCORE` | `docs/evidence/_v15_stage8/g6_ruling/adjudication_composition_ruling.md` |
| 中 | G8 的入口形状一条，与 §4.1b 硬规则 2 对齐后交裁决 | `docs/evidence/_v15_stage8/adjudication_q5_baseline.md` |
| 中 | G3 更新 `ACCEPTANCE_STATUS.md:1475-1478` 的旧读数（36 GB → 18.25 GiB ＋ work/ 49.39 GiB），并给用户手工删除清单 | `docs/knowledge/ACCEPTANCE_STATUS.md` |
| 低 | G5/G9/G7/E2 四条结案，写进 `OPEN_ITEMS_20261007.md` §六 的"已收口"栏（防它们被再次点名） | `docs/knowledge/OPEN_ITEMS_20261007.md` |
| 低 | 在 `ACCEPTANCE_STATUS.md:1940-1942`（§28.1 的"还没做"）加一条指向 `:2168` §29.4 的编者注，避免下一个人再被旧表述骗一次（本卡的仪器就是这么被骗的） | `docs/knowledge/ACCEPTANCE_STATUS.md` |

**本卡完成定义对照**：□ 9 条逐条核查（＋E2 共 10 条）**已做** □
每条给"文件:行号 / 命令 / 真实输出"**已给** □ 属实的只出提案、涉判据/换代标 ⚖️
**已做** □ 一处代码都没改 **已守**。
