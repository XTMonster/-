# `20261007-v15-zerocand-verdict` — 零候选槽位的**裁决记录**（qwen3.8-max-0902 代替人工裁决）

用户 2026-10-07："用拍板的问题 2 的那个 qwen3.8max0902 解决，**代替人工裁决**"。
这一份就是那条裁决：**逐条判完 199 个零候选槽位**，`reviewed_by: "third-party"`。

## 1. 判的是什么

零候选槽位 = 该成员的取值 surface 在**全库任何卡**正文里都找不到（`rebind/v2` 口径下
**199** 条，含 `axis_side` 一族）。机械重绑修不了它们，所以只剩"留着还是摘掉"这一个问题。

**判官**：`qwen3.8-max-0902`（**阿里云百炼**，DashScope OpenAI 兼容口），
`reasoning_effort=max`，流式；18 批（66 条自然语言 surface 逐条 ＋ 133 条闭集词元逐条），
每批一份 `裁决.json` ＋ `.usage.json`（模型、档位、耗时、token）。组题脚本
`work/_zerocand_batches.py` / `work/_zerocand_batches_rest.py`，汇总
`work/_summarize_zerocand.py`。

## 2. 判词（`verdict.json`）

| 判词 | 条数 | 含义（题包里写死的口径） |
|---|---|---|
| `keep` | **177** | 取值本身站得住；卡里没有这个串是**良性**成因（闭集词元 / 蕴含未写出） |
| `wrong_card` | **20** | 这条边的来源卡**主题**与取值不是一回事 ⇒ 建议把这个成员摘掉 |
| `wrong_value` | **2** | 取值本身抄错/编错 ⇒ 建议把这个成员摘掉 |

逐条理由在 `verdict.json` 的 `rows[].why`（≤25 字）。非 keep 的集中在
`vfx`（7）／`sfx`（7）／`pacing`（3）／`lighting`（2）／`headroom_policy`（2）／`beat_type`（1）。

## 3. **裁决已出，但执行被冻结的 oracle 挡住**（`apply: false`，如实写）

规则本来已经写好（`tools/kb_fetch/rebind.py::prune_members`，`prune/v1`：
判成 `wrong_card`/`wrong_value` 的成员从它所属的边上摘掉；边被摘空就整条删），
但**没有打开**：

```
22 条判决**逐条**试过（work/_prune_greedy.py，每次都重跑门①–⑩）：
  任一条单独执行 ⇒ 门⑩ 判红，unresolved 2–67 条
  （原因：门⑩ 的 spec 是按**边的成员形状**匹配的，每个成员都是某条 spec 期望的形状的一部分）
基线（一条都不摘）⇒ 门⑩ pass
```

要执行它就必须改**冻结的 held-out 夹具**（删掉那些 spec）＝ 一次 **oracle 换代**：
那会让所有已入库运行的夹具 pin 一起失配（它们的 pin 里就有夹具 sha256），
整条链与真跑都要重来一遍。**所以这一条停在"裁决已出、执行待授权"**，
记录里 `apply` 显式为 `false`（缺省也是 false；索引不会因为躺在别处的一份记录而悄悄改）。

## 4. 复算

```
python -c "import json,pathlib;d=json.loads(pathlib.Path('docs/evidence/20261007-v15-zerocand-verdict/verdict.json').read_text(encoding='utf-8'));print(d['counts'], d['apply'])"
  -> {'keep': 177, 'wrong_card': 20, 'wrong_value': 2} False
python work/_prune_greedy.py     # 逐条试"执行会不会破门⑩"（末尾把索引复原成 v2）
  -> accepted 0 / rejected 22, restored_v2: true
```
