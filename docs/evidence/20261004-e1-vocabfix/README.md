# E1 的一次**实验**（未发货）：把线索词表换成产品真源表

> **状态：实验记录，不是已发货的改动。** 这一份里的 `reviews.jsonl` 是站在
> **工作区副本**（`work/armB/`：810 条案例 ＋ 363 条词表同源的新线索）上跑出来的，
> 它**没有**进 `knowledge/`。为什么不发货：glm-5.3 会诊（`work/_consult_e1/`）的 F3
> 指出 **17/192 与 23/192 的差在二项噪声下只有约 1 个标准误**——单跑一次的 A/B
> 撑不起结论。噪声底（A/B 各 3 次、交替跑）落在 `work/e1_noise_floor.log`，
> 结果出来之前这一页只是"看到了一个方向"，不是"拿到了一个改进"。

## 这一次量到了什么

同一部片子、同一批 64 条逐镜中文查询、同一份 810 条案例语料，**只改生成线索时
给模型的那份闭集词表**（从提示词里手写的一小串，换成
`tools/kb_fetch/vocabulary.py` 的真源派生）：

| | A：旧提示词 | B：词表同源 |
|---|---|---|
| 线索条数 | 739/810 | **363/810** |
| 查询点名却在整库线索里找不到的工艺词 | 153/309 = 49.5% | **104/309 = 33.7%** |
| E1（跨族面板，64 查询 × top-3） | 17/192 = 0.0885 | **23/192 = 0.1198** |
| 一条 ≥4 都没有的查询 | 47/64 | 42/64 |

两个独立读数同向（缺口少 49 处、E1 多 6 条），但**样本量不足**（见上）。
`reviews.jsonl` = B 臂那一次。

## 同批的**负结果**（省得以后再试）

在冻结的 B 臂索引上只换检索串的形状（`--queries`，64 条一一对应）：

| 查询形状 | E1 |
|---|---|
| 散文（产品现行：`shot.prompt`） | **23/192 = 0.1198** |
| 契约串（`景别=LS；镜头=50.0`，超图那一栏的形状） | 1/150 = 0.0067 |
| 契约串 ＋ 散文 | 19/192 = 0.0990 |

⇒ **查询形状不是杠杆**：L3 的案例库按散文线索建键，换成 `键=值` 等于换了门语言
（那一栏本来归超图 L1/L2 管）。

## 复算

```powershell
python docs/evidence/20261004-e1-vocab/e1_vocab_probe.py --cases-dir work/armB `
    --project docs/evidence/20261004_chunked_long19/project/project.bdproj --json
python tools/knowledge/e1_panel.py `
    --project docs/evidence/20261004_chunked_long19/project/project.bdproj `
    --cases-dir work/armB --out <out> --top-k 3 --workers 4
```

会诊的**原始回包与它看到的逐字 bundle**在 `work/_consult_e1/`
（`bundle.md` / `bundle.manifest.json` / `实现顾问.json` / `实现顾问.usage.json`）。
