# `20261007-v15-long` — `rebind/v2` 换代后的长剧本真实运行（**触顶如实报出来**）

这一跑是知识索引换代（`rebind/v1` → `rebind/v2`，见
`docs/knowledge/REGEN_LOG_20261007_rotation.md` §7）之后的长剧本真跑，用来替换
`20261003_real_long` / `20261006-long21` 当本代的"长路径 + Q5/E2 运行侧"证据。

## 1. 这一跑是什么

| 项 | 值 |
|---|---|
| `run_id` | `c923e61e0c28` |
| 终态 | `DONE`（`success: true`） |
| 剧本 / 预设 | `fixtures/script_long_61.md` / `fhd16x9` |
| 镜数 / 总帧 | 64 / 4584 |
| 步骤 / LLM 调用 / 工具调用 | 675+ / **326** / —（调用硬顶 `shots*8+40 = 552`） |
| 检索调用（`retrieval_call`） | **67** |
| 知识后端 | `hypergraph`（2353 张卡、`lanes=2`、`degraded=false`） |
| 索引代际 | `hypergraph_fingerprint = e5213e1b64781c24103eecae15a4921b5766f75c4709672fa48997de692cdf89` |
| 交付 | 133 个文件（64 段 mp4 ＋ 首帧 ＋ `blockout_full.mp4` ＋ `shots.json` ＋ `prompts.md` ＋ `README.md`） |

## 2. **这一跑触顶了 token 上限（如实记，不当作已通过）**

```
{"llm_calls": 326, "prompt_tokens": 1886634, "completion_tokens": 118326,
 "total_tokens": 2004960,
 "limits": {"max_llm_calls": 552, "max_tokens": 2000000, "max_cost_usd": 5.0,
            "max_wall_seconds": 7200.0},
 "exhausted": "token 用量已达上限（2000000）"}
audits 162 / failed_audits 92 / repairs 68 / audit_pass_rate 24/56
```

`tests/test_extract_run_evidence.py::test_the_long_real_run_is_fresh_and_stayed_within_the_ceiling`
里那句 `assert not payload["budget"]["exhausted"]` **因此判红**——判据一个字没改，
红的就是当前代码的真实读数。**同一份剧本连跑两次都触顶**（本份 `c923e61e0c28`
2,004,960；第一次 `7053f80d4fa5` 2,000,574，见
`docs/evidence/20261007-v15-long-topped-out/`），所以这不是抽样运气：

| 运行 | 镜数 | 调用 | total_tokens | token/调用 | 触顶 |
|---|---|---|---|---|---|
| `20261003_real_long`（v1.4 时代） | 64 | 213 | 723,286 | 3,396 | 否 |
| `20261007-v15-long`（本份） | 64 | 326 | 2,004,960 | 6,150 | **是** |
| `20261007-v15-long-topped-out` | 64 | 317 | 2,000,574 | 6,311 | **是** |

`max_tokens = 2_000_000` 是 `block_director/layer5_orchestrator/budget.py` 里
`LedgerLimits` 的**代码默认值**，`specs/config.default.yaml` 里**没有**这一格
（与 `budget.max_llm_calls_per_scene_formula` 那种"随镜数缩放"的口径不同）。
v15 的提示词变长（意图轴 + rulepack + 场景状态）＋ 返工变多（`failed_audits 92`）
之后，64 镜真跑稳定落在 2.0–2.1 M。**要不要抬这个上限、要不要让它随镜数缩放，
是阈值决策**（R-5），所以这一份只如实记读数，不替用户改。

## 3. 怎么跑的（可复现）

```
python tools/sidecar_server.py --host 127.0.0.1 --port 8773 \
  --upstream https://api.deepseek.com --upstream-kind openai --model deepseek-chat \
  --upstream-api-key-env DEEPSEEK_API_KEY --knowledge-dir knowledge \
  --cases-backend hybrid --temperature 0 --seed 0 --timeout 600

blender --background --factory-startup --python tools/run_headless.py -- \
  --sidecar --script fixtures/script_long_61.md --build --preset fhd16x9 \
  --out docs/evidence/20261007-v15-long \
  --save docs/evidence/20261007-v15-long/project \
  --export --export-dir docs/evidence/20261007-v15-long/export \
  --wall 9000 --llm-timeout 300 --max-llm-calls 0
```

## 4. 复算

```
python tools/extract_run_evidence.py --out docs/evidence/20261007-v15-long --check
  -> {"ok": true, "reasons": [], "warnings": []}      # 同代、契约自洽
```

**同代没问题**（`check` 零原因零警告）：这一份完全可以用作本代的 Q5/E2 运行侧输入
（链上 `$knowledgeRun` 指的就是它）。**唯一红的是那条"未触顶"判据。**
