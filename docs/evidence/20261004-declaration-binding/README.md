# P14-91：**分镜表声明的拍摄手法是锚**——Q5 第一次 pass，交付同时更好

## 改了什么（一处入口）

`editor.merge_camera(declared_move, planned, drafted)`：相机字段的合并规则，
`merge_dialogues` 的相机版（同一条纪律"声明的必须落实"）：

* **没声明**手法 ⇒ 草案自由（老行为，空 `movements` 不覆盖）；
* 声明 **`static`（固定镜头）** ⇒ 草案**不许**给这一镜加运动（只借 side/lens 等）；
* 声明了**具体手法** ⇒ 以声明为准（草案给了别的运动也不换）。

原来 `_pin_declared_camera` 只做"声明了非固定手法而草案没给 ⇒ 钉上"，而 `static`
因为"引擎运镜词表里没有'固定'"被跳过、草案自创的运动照单全收——所以"声明固定"
这一档**没有任何环节去落实或核对**（§八十五）。

## 先离线模拟（零 LLM，三份冻结工程）

`binding_probe.py` 在同一趟 Blender 里跑两臂：交付原样 vs **去掉未声明的运动后重建**。

| 工程 | 去掉的镜 | 逐镜通过 | 构图门（≥70） | 构图分中位 |
|---|---|---|---|---|
| long17 | 40 | 29 → **35** | 44 → **55** | 85.6 → **89.5** |
| long15 | 39 | 27 → **29** | 35 → **39** | 71.4 → **77.4** |
| long18 | 41 | 22 → 22 | 31 → **33** | 66.5 → **72.5** |

⇒ **忠于分镜表同时更好**（三份工程两个指标都不退，多数明显更好）。

## 再真跑一次（long19，同一份剧本、同一条命令、同一后端）

| | long17（改前） | **long19（改后）** |
|---|---|---|
| 终审逐镜通过 | 33 | **45** |
| 错误分布 | R001 27、COMPOSITION 16、R003 1 | **COMPOSITION 10、R001 8、R003 5** |
| 构图分中位 | 85.6 | **88.0** |
| 构图门（≥70） | 48 | **54** |
| 交付里有运动的镜头 | 41 | **1**（就是那一镜自己声明 `dolly_in` 的） |
| **声明固定却有运动** | **40** | **0** |
| **Q5（链上口径）** | 9 / 12 ＝ 0.75（fail） | **11 / 11 ＝ 1.0（pass）** |
| token | — | 1 563 166（上限 2 000 000，未触顶） |

复算：

```
python docs/evidence/20261004-declared-vs-delivered/probe.py docs/evidence/20261004_chunked_long19
python tools/knowledge/quality.py --run-id 967c2068499a --audit-run-id 967c2068499a --json \
    --cases knowledge/cases.jsonl --e1-reviews docs/evidence/20261003-e1-zh/reviews.jsonl \
    --shots docs/evidence/20261004_chunked_long19/shots.json \
    --audit-log docs/evidence/20261004_chunked_long19/audit_log.jsonl --out <json>
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261004_chunked_long19/project   # → 通过 41 / 中位 86.5（零 LLM 复评）
```

**Q5 为什么现在 pass，要说清楚**：这一版剧本为 63 镜声明"固定镜头"，而标注对这几组
`景别×意图` 的期望也正是 `固定`——交付忠于声明，于是也就落进了标注的期望里。
join 键仍取自 `audit_log.jsonl` 的逐镜 `retrieval_call`（§4.1b 硬规则 2），
标注是独立写的，**判据、门限、oracle 一个字没动**。（若剧本声明的是别的运镜，
这里不会因为"全片静止"而变绿。）

## 守门

`tests/test_compliance.py::test_a_declared_static_shot_loses_the_drafts_invented_movement`：
market 夹具里 4 镜声明固定 → 草案硬塞 `dolly_in` → 计划里那 4 镜的运动必须被清空；
声明了 `dolly_in` / `follow_subject` 的两镜仍必须有运动（反面）。既有台词 pin 的
那条用例（`test_declared_dialogue_is_pinned_and_survives_a_rewriting_draft`）不动。

`tools/run_tests.ps1` **32/32**、`python -m pytest` **2007 passed / 1 skipped**，
链账 `docs/evidence/20261004-135244/`（硬门口径不变：Q5 现在 pass，链上只剩 E1）。
