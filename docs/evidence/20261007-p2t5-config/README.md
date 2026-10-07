# 卡 P2-T5（配置项与 gen_specs）执行证据

**执行者**：子 agent `c_config`（主线派发）
**HEAD**：`f6530c6`（docs(P14-319)）＋本卡未提交改动
**卡文**：`执行文档v1.5/EXECUTION_PLAN.md` 卡 P2-T5；判据来自同目录 `TDD.md` §7

措辞约定：本文件凡标「实测」的都有命令与输出；推断一律写明「推断」。

## 1. 落地内容（三键）

| 键 | 缺省 | 校验 | 落点 |
|---|---|---|---|
| `rag.rule_top_k` | `5` | int 且 3–8 → **CFG_020** | `block_director/contracts/config.py:94` |
| `vlm_review.enabled` | `false` | bool（无需额外校验） | `block_director/contracts/config.py:146` |
| `vlm_review.max_shots` | `0`（不限） | int ≥ 0 → **CFG_021** | `block_director/contracts/config.py:147` |

`orchestration.draft_candidates` 按卡文**本卡不加**（P6-T2 落地）。

## 2. 报错码选用与不撞号证据（实测）

改前 `rg -no "CFG_0[0-9][0-9]" block_director/` 的结果是 **CFG_001…CFG_019 连续占满**
（另有 101/102/103、201…214、301…306 三段，与 `CFG_0xx` 序列无关）。
⇒ 序列下一个空号是 **CFG_020**，再下一个是 **CFG_021**，本卡各用一个。

改后同命令显示 CFG_020/021 **只出现在** `config.py:410` / `:416`；
`rg -n "CFG_020|CFG_021"`（排除 `docs/`）除本卡代码与测试外**无其他引用**。

> 说明（推断，非实测）：`VlmReviewConfig.max_shots` 的 ≥0 校验是 TDD §7 表格
> 明确列出的判据；卡文步骤 1 只点名了 `rule_top_k` 的码，故 max_shots 用
> 紧随其后的空号 **CFG_021**，不借用语义相同但字段不同的 CFG_016。

## 3. 验收命令与输出

```
python -m pytest tests/ -q -k "config or specs"        # EXIT=0
  ........................................................................ [100%]

python -m pytest tests/ -k "config or specs" -v        # 取汇总行
  ===================== 72 passed, 2467 deselected in 4.66s =====================

python -m pytest tests/test_config.py tests/test_config_vlm_review.py   # 52 通过
```

（pytest 9.1.1 在 `-q` 下不打印汇总行，故另跑一次默认 verbosity 取 `passed` 数。）

## 4. 规格同步与幂等（红线 R-4，实测）

```
python tools/gen_specs.py            -> [OK] 已生成 specs/config.default.yaml（2346 字符）
python tools/gen_specs.py --check    -> run1=0
python tools/gen_specs.py --check    -> run2=0
```

`git diff specs/config.default.yaml` 只含新键（无既有行被改）：

```
+  rule_top_k: 5
+vlm_review:
+  enabled: false
+  max_shots: 0
```

## 5. 改动文件清单

* `block_director/contracts/config.py`（M，+32）
* `specs/config.default.yaml`（M，+4，由 `tools/gen_specs.py` 生成）
* `tests/test_config_vlm_review.py`（新增）

`git diff --stat`：`config.py | 32 ++++`，`config.default.yaml | 4 +++`，共 36 行新增，0 删除。

## 6. 向后兼容（实测）

* 旧配置文件缺这两个键 ⇒ `AppConfig.from_dict` 回落到缺省（`test_a_config_without_the_new_keys_falls_back_to_defaults`）。
* `to_dict`→`from_dict` 往返稳定（`test_new_keys_round_trip_through_serde`）。
* 两键目前**零消费者**（`rg "rule_top_k|vlm_review"` 改前无命中）⇒ 运行时行为零变化；
  消费者分别由 P4-T1（rulepack）与 P6-T1（VLM 评审）落地。

## 7. 未验证 / 剩余风险

* **未跑全量 `python -m pytest`**，也**未跑阶段门 G2**：卡文明确「不要跑全量 pytest」，
  G2 由主线在三阶段（P2-T1…T5）全部落地后集中跑——其中 SDL 1.4 兼容与 golden
  `--check` 不由本卡负责。本卡只证明「配置这两键 + specs 同步 + 相关测试」绿。
* **未跑 `tools/run_tests.ps1`**：同属主线阶段门，本卡不触发。
* 未提交任何 git commit（卡文要求）。
