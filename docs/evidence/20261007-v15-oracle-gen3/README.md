# `20261007-v15-oracle-gen3` — 执行"22 条裁决"的全过程与**实测结论**（用户 2026-10-07「跑吧」）

用户批准："那 22 条裁决要不要通过一次 oracle 换代来执行" → **跑吧**。这一份是**跑完的读数**：
结论是 **这两条执行路都撞在硬门上**，所以最后**回滚到已验证状态**，把判决留在案上，
并把"为什么不能这么执行"逐条量了出来。

## 1. 做了什么（按顺序，每步都有产物）

| 步 | 动作 | 产物 / 读数 |
|---|---|---|
| 1 | 按裁决剪枝（摘 22 个成员；schema 残缺的 17 条边**整条去掉**） | 638 → **621 条边**，指纹 `6e7b87ab…` |
| 2 | 用 `tools/knowledge/holdout_drop_pruned.py` 改 oracle：摘掉**因为剪枝而解析不到**的 spec | `holdout_drop_pruned.json`：**141 条 spec**（must 28 ／ top1 28 ／ never 85）＝ 门⑩ 逐条报出来的那 141 条，**未归因 0**；**28 条条目**因此空掉（`must`/`top1` 被摘空） |
| 3 | 3 张卡掉了唯一一条条目 ⇒ 用 **qwen3.8-max-0902（百炼）** 从卡正文重写 | `refill3/标注.json`（3 条，形状逐字取自各卡自己的边） |
| 4 | 门③/门④ 因剪枝掉出缺口 ⇒ 用仓库既有的补跑件（`build_gap_prompt`/`absorb`）补标注 | `work/_topup_drive.py`：4 轮、**+52 条**（2874 条），随后门④ 转绿 |
| 5 | 仍然红：**门③** | 见下 |

## 2. 实测结论：**"摘成员"这个动作在结构上执行不了**

被摘的 22 个成员里 **17 个是必填槽位**（`ACTION_BEAT.beat_type`、`IMPACT_PACK.vfx`…）。
两条路都试过：

**(甲) 把 schema 残缺的 17 条边整条去掉**（第 1 步的做法）

```
门③ fail：missing_values = {movement: [crane_arc_down, crane_arc_up, dolly_zoom,
                                        whip_pan_right],
                            sfx: [尖锐哨音, 金属撞击]}
```

这 6 个取值**在索引里再没有载体**（它们只出现在被去掉的那 17 条边上）⇒ 查询里点名它们
也命中不了任何边 ⇒ **补标注补不回来**（门③ 要的是"词表无盲点"，不是"有几条条目"）。

**(乙) 保留那 17 条边、只摘成员**（第 1 步的替代做法）

```
索引 638 条边（22 个成员被摘、17 条边 schema 不完整）
card_scope：edge_backed 2262 / excluded 91 / **edge_backed_without_entry = 17**
```

那 17 张卡的边**全部**都是这些残缺边（脚本实测：每张卡的"完整边数"都是 **0**）——
而 spec 必须声明该类型的必填槽位（`check_holdout.parse_spec` 的 `REQUIRED_SLOTS`）⇒
**写不出任何一条能解析的 spec** ⇒ 门⑥（每张可断言卡至少一条条目）红。

## 3. 结论与回滚

⇒ 这 22 条判决的正确执行形状**不是「摘成员」**，而是**让这些成员有真来源**：
要么**重抽取**（`--replace-cards` 一轮——但那是"重新掷骰子"，
见 `tools/kb_fetch/rebind.py` 的模块文档），要么**连同词表一起换代**（会把真实取值从词表里删掉）。
两条都要用户明示。

因此本轮**回滚**（`work/_revert_gen3.py`，确定性：裁决 `apply:false` ＋ 构建器重建 ＋
三个夹具从 HEAD 逐字节取回）：

```
索引指纹 e5213e1b…（rebind/v2，0 条剪枝）
held-out sha e3e6bac2…（2847 条，gen2）
card_scope 2262 / 91 / 孤儿 0
门①–⑩ overall: pass　　Q1–Q7 passed
```

判决记录本身的 `apply_blocked_by` 已经把上面两条实测写进去（
`docs/evidence/20261007-v15-zerocand-verdict/verdict.json`）。
