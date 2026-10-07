# G3/G4 在**最终 HEAD** 上的复审（2026-10-07 收尾）

`docs/evidence/20261007-g3/` 与 `docs/evidence/20261007-g4-forbid-guard/` 的原始读数
出自 P3/P4 那一批（当时索引还是 `c796a5a8…`）。收尾时（HEAD `a4ab1ce`，索引已换代到
`e5213e1b…`）把两个阶段门**原样重跑**一遍，确认换代与后续改动没有动它们：

## G3（三份冻结工程逐镜四元组）

命令（与 `../README.md` 的「之后」逐字相同）：

```
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261003_chunked_long9/project  --out ...
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261004_chunked_long11/project --out ...
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261004_chunked_long12/project --out ...
```

| 冻结工程 | 逐镜通过 | 构图分中位 | R 系列 | 与 `../long*.json` 的逐镜四元组 |
|---|---|---|---|---|
| `long9` | 29（原 29） | 79.6（原 79.6） | `COMPOSITION 25 / R001 11 / R003 1` | **identical_rows=True** |
| `long11` | 8（原 8） | 64.3（原 64.3） | `COMPOSITION 40 / R001 40` | **identical_rows=True** |
| `long12` | 24（原 24） | 72.4（原 72.4） | `COMPOSITION 30 / R001 7 / R003 7` | **identical_rows=True** |

## G4（forbid 守门：`forbid_members_seen > 0` ＋ 排名未动）

```
python docs/evidence/20261007-g4-forbid-guard/g4_forbid_guard.py > recheck_final_head.json
  -> forbid_members_seen=217, top1_preserved=103/103, top1_is_backfilled=0,
     gate_g4 = {forbid_members_seen_gt_0: true, ranking_preserved: true}
```

**为什么这一次才是"同代"的**：`../README.md` 的前提是"当前工作树的索引与那些冻结运行同代
（`c796a5a8…`）"；换代之后那条前提已不成立，所以必须在**现行索引**（`e5213e1b…`）上重放。
重放结果**逐项相同**：换代（重绑 ＋ 裁决留痕）**没有动检索名次**。
