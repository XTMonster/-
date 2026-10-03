# E1：把中文线索从"摘要形状"改成"查询形状"——**实测未提升**

这份目录是 `P14-44`（`9464923`）留下的那句"效果未测"的答案：那次提交只声明
**形状**对了，E1 会不会动，本目录按同一条跨族面板把它量出来。结论先说：

```
旧臂（入库线索，v1 摘要形状，739 行）  3 / 2 / 3   →  8/54 = 0.1481
新臂（v2 查询形状，429 行，53.0% 覆盖） 2 / 3 / 3   →  8/54 = 0.1481
```

**没有提升** ⇒ 按 lane 的规矩，候选产物**不入库**：`knowledge/cases.search_zh.jsonl`
保持 HEAD 的 v1 产物，0.70 的门限一个字没动，`tools/run_tests.ps1` 的 `--e1-reviews`
也没换（打分文件没有换代）。

## 1. 被测对象（两臂只差"线索文件"这一件事）

| | 旧臂 | 新臂 |
|---|---|---|
| `cases.jsonl` | 810 条，`fingerprint 69791dba…`（两臂**同一份**） | 同左 |
| 线索文件 | 入库的 `knowledge/cases.search_zh.jsonl`（739 行） | `work/e1_query_shape/candidate/`（429 行） |
| 生成模型 / 提示词 | glm-4.7 / v1（"改写成一句中文线索"＝摘要形状） | glm-5.3 / v2（"先说**要拍什么**，再说摘录里的做法"＝查询形状） |

新臂的生成账（`coverage.json`）：

```
第一轮 810 条：written 333 / dropped 477（call-failed 204 ＋ empty 273）
定向重跑   204 条 call-failed：回收 96 条
合计       429 行 / 810 = 52.96% 覆盖（丢弃：call-failed 225 ＋ empty 360）
按来源：site 289/497、gutenberg 139/301、mit_ocw 1/12；429 行里 327 行含工艺词
```

`empty` 是 v2 的**设计行为**（摘录确实不含拍摄工艺信息时给空串，不硬编）；
`call-failed` 是上游抖动（14 并发下首轮失败率 25%——这条是这次跑出来的新事实，
已让 `--dropped-out` 带上异常类型、并加 `--retry-from` 只重跑瞬时失败）。

## 2. 面板与查询（与 §4.1b 的口径一致，只换了不可用的 glm-4.7）

* 查询 = 一次真实运行的 6 条逐镜散文（`docs/evidence/20261002_real/project/project.bdproj`），
  `tools/knowledge/e1_panel.py --project …` 抽的就是它；
* 面板 = `deepseek-chat` ＋ `glm-5.3`（跨族；glm-4.7 已 429 余额不足）；
* 单位 = 每条被返回的案例 1–5 分，`≥4` 记相关；每次运行 = 6 问 × top-3 = **18 条分母**
  （六次运行分母全是 18，没有靠"分母塌掉"换比率）。

## 3. 为什么没提升：**不是变差，是重排**

把两臂索引的 top-8 摆在一起（面板分来自上面六次运行）：

| 查询 | 旧臂 top-3（面板分） | 新臂 top-3（面板分） |
|---|---|---|
| Q5 偷盗者奔逃…跟拍…魔法生效 | storyboard-arrows 3.5–4.5 ／ storyboard-rules 2.5–3.0 ／ **steadicam 4.0** | storyboard-arrows 3.5–4.5 ／ storyboard-rules 2.5–3.0 ／ **25_008 1.5–2.0**（steadicam 掉出 top-8） |
| Q1 码头市场建立镜（187 字） | pg45714 1.0 ／ rack-focus 2.5–3.0 ／ establishing 3.5 | pg55346 2.0–2.5 ／ 75_075 2.0–2.5 ／ pg45714_362 1.0（establishing/rack-focus 掉出前八） |
| Q4 手部特写…调皮神态 | blocking 2.0–2.5 ／ pg13928 3.0–3.5 ／ pg10865 1.0–1.5 | blocking 2.0–2.5 ／ 134_026 1.0 ／ **types-of-camera-shots 3.5** |
| Q6 停下脚步…表情转为狂喜 | pg56570 1.5 ／ logic-of-disorientation 1.0–1.5 ／ low-angle 2.0 | pg56570 1.5 ／ pg57239 1.0 ／ **types-of-camera-shots 3.5** |

三条判读：

1. **≥4 的命中始终是同样三条技术页**（`eyeline-match_023`、`eyeline-match_008`、
   `steadicam_005`）——查询形状把词表对齐了，但语料里"能照做"的条目就那么几条；
2. **重排有代价**：Q5 里唯一 ≥4 的 `steadicam_005` 被挤出 top-8；Q1 里最好的两条
   （3.5 / 2.5–3.0）也掉出前八，换上的是 2.0–2.5 的碎片——"要拍…"这个句式把
   **查询语域的通用词**也带进了每一条线索，噪声同样受益；
3. **有两条 3.5 的新面孔**（Q4/Q6 的 `types-of-camera-shots`）——方向是对的，但
   3.5 仍然在线下；要跨过 0.70，缺的不是"键的形状"，而是**排序面**（对 top-k 做
   语义/可用性判别）或**语料面**（把这批 1900 年代散句换成逐镜分析类的来源）。
   两者都在本 lane 的白名单之外（`block_director/**`、`knowledge/cases.jsonl`）。

## 4. 复算命令

```powershell
# 生成（新臂；密钥只从环境变量读，绝不入库）
$env:GLM_API_KEY='<env>'; $env:GLM_THINKING='max'
python -X utf8 -m tools.kb_fetch.case_search_zh --provider glm --model glm-5.3 `
    --cases knowledge/cases.jsonl --out work/e1_query_shape/candidate/cases.search_zh.jsonl `
    --dropped-out work/e1_query_shape/candidate/dropped.jsonl --workers 14
python -X utf8 -m tools.kb_fetch.case_search_zh --provider glm --model glm-5.3 `
    --cases knowledge/cases.jsonl --out work/e1_query_shape/candidate/cases.search_zh.jsonl `
    --dropped-out work/e1_query_shape/candidate/dropped_retry.jsonl `
    --retry-from work/e1_query_shape/candidate/dropped.jsonl --retry-reasons call-failed `
    --workers 8

# 影子索引（两臂）＋六次面板
Copy-Item knowledge/cases.jsonl, knowledge/cases.manifest.json work/e1_shadow_old/knowledge/
Copy-Item knowledge/cases.search_zh.jsonl work/e1_shadow_old/knowledge/cases.search_zh.jsonl
Copy-Item work/e1_query_shape/candidate/cases.search_zh.jsonl work/e1_shadow_new/knowledge/cases.search_zh.jsonl
#   两臂的 cases.jsonl / cases.manifest.json 都是 knowledge/ 的逐字节副本
1..3 | ForEach-Object { python -X utf8 tools/knowledge/e1_panel.py `
    --project docs/evidence/20261002_real/project/project.bdproj `
    --cases-dir work/e1_shadow_old/knowledge --models deepseek-chat,glm-5.3 `
    --out docs/evidence/20261003-e1-query-shape/old_run$_.jsonl --json }
#   new_run1..3 同形，只把 --cases-dir 换成 work/e1_shadow_new/knowledge
```

`old_run*.jsonl` / `new_run*.jsonl` 是**原始面板记录**（逐条 case_id、query、zh 线索、
excerpt、两个模型的分数、面板名与索引指纹）；`coverage.json` 是候选产物的生成账。
