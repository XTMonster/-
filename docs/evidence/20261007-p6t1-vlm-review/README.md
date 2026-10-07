# 证据 · P6-T1 VLM 评审外回路（默认关）

**run-id**：`20261007-p6t1-vlm-review`
**卡**：`执行文档v1.5/EXECUTION_PLAN.md` → P6-T1（VLM 评审外回路，可选、默认关）
**HEAD**：`f6530c6` ＋ 本版未提交改动
**执行者**：主线（DeepSeek）
**纪律**：R-1（契约层不 import bpy）、R-2（碰 bpy 的走 `@main_thread_only`）、
R-5（判据/门限一个字没动）。

---

## 1. 交付物

| 半边 | 文件 | 说明 |
|---|---|---|
| 纯契约层（无 bpy） | `block_director/contracts/vlm_review.py` | rubric、取帧号、请求装配、响应解析、**重试一次后放弃**的策略 |
| 引擎侧（bpy） | `block_director/layer3_engine/shot_auditor.py` | 取首/中/末三帧 → 调评委 → 还原现场 → 挂 `AuditResult.vlm_review` |
| 契约字段 | `block_director/contracts/audit.py` | `vlm_review: Optional[Dict]`（缺省 `None` ⇒ 形状零差） |
| 传输契约 | `block_director/contracts/messages.py` + `specs/openapi.yaml` | `Message.content` 放宽为 `string \| array \| null`（vision 请求体要求分片数组） |
| 交付物 | `block_director/delivery/manifest.py` | 有判词才写 `shots[].vlm_review`（**没有"查过但空"这个状态**：没评过就是没这个键） |
| 面板 | `block_director/layer7_ui/panel_shots.py` | "查看审核结果"里展示分数／跳过原因 |
| 接线 | `layer5_orchestrator/modal_operator.py`、`headless_runner.py`、`tools/run_headless.py` | GUI 与 headless 两条通路都把 `config.vlm_review` 与同一条 transport 交给审核器 |
| 单测（纯） | `tests/test_vlm_review.py`（34 条） | 见 §2 |
| 单测（Blender） | `tools/blender_tests/test_vlm_review.py`（5 条） | 见 §2 |

## 2. 实测读数（命令 ＋ 输出）

```
python -m pytest tests/test_vlm_review.py tests/test_openapi_matches_contracts.py \
    tests/test_best_of_n.py -q         -> exit 0（114 passed，输出见同目录 pytest_vlm_review.txt）

blender --background --factory-startup --python tools/blender_tests/test_vlm_review.py
  -> BD_TEST_RESULT {"passed": [disabled_review_is_byte_identical,
                                enabled_review_renders_three_frames,
                                the_review_never_moves_the_gate,
                                unavailable_judge_is_recorded_as_a_skip,
                                max_shots_caps_the_review_but_records_it],
                     "failed": []}
```

五条探针钉住的事（原始输出见 `probe_vlm_review.txt`）：

1. **默认关零差**：`audit()` 的 `to_dict()` 键集是
   `errors/justification_audit/level/passed/score/suggestions/target/warnings`
   ——**没有** `vlm_review`；`judge_calls = 0`（一次渲染、一次调用都没有）。
2. **打开真的取三帧**：`frames = ["first", "middle", "last"]`，请求里
   **3 个 `image_url` 分片**，`purpose = review`；渲染现场（当前相机／帧／
   输出路径）跑完**逐字段还原**。
3. **判词不是门**：同一镜关着 / 开着两次审核，`passed` / `score` /
   `errors` / `warnings` / `justification_audit` **逐字节相同**
   （实测 `score = 92.4`，两次都一样；评委故意给 1 分也不动判定）。
4. **评委不可用 ⇒ 跳过并记录**：两次 `TransportError` 后
   `{"status": "skipped", "reason": "评委不可用（重试一次后放弃）",
   "attempts": 2, "error": "…429"}` —— **没有 `score` 键**
   （跳过绝不写成 0 分）。
5. **`max_shots` 到顶**同样如实记跳过（`reason` 里点名上限），
   且汇总里 `reviewed 1 / skipped 1` 分得开。

## 3. 与卡文不符之处（执行记录，按 README 使用规则第 4 条如实登记）

卡 P6-T1 的写集只列了 `block_director/layer3_engine/shot_auditor.py`。按现状代码，
"结果只进 shots.json 与面板"这句话落不到那一个文件上：判词要进 `shots.json`
必须经过 `contracts/audit.py`（结果字段）、`delivery/manifest.py`（交付物）与
`layer5_orchestrator/driver.py`（把判词从审核结果转写到 `build_summary`）；
"面板展示"在 `layer7_ui/panel_shots.py`；"默认关"要能真读配置，必须接
`modal_operator.py` 与 `tools/run_headless.py` 两处构造点。

**这不是设计改动，是写集登记不全**：与 P4-T4（同一卡型：对照结果要进
`shot_audit` ＋ `shots.json`）当年的实际改动面一致——那一卡同样动了
`contracts/audit.py` / `driver.py` / `delivery/manifest.py`。
判据、门限、阈值一个字没动（R-5）。

## 4. 未验证 / 边界

* **没有跑真实 VLM**：本卡验收只要求"mock transport 单测全绿 ＋ 默认关零回归"，
  实测即如此。真实评委的连通性、图像 token 成本、1–5 分的稳定性**均未验证**；
  评委不可用的退路（跳过并记录）已按卡文实现并单测。
* **`vlm_review.enabled=true` 的全链路跑**未做：它需要真实 VL 端点
  （`DEEPSEEK_API_KEY` 可用，但是否支持 vision 未核）＋ 每镜 3 张 PNG 的渲染
  成本。命令形状：`blender --background --python tools/run_headless.py --
  --build --export` 配 `vlm_review.enabled: true` 的配置；
  结果会落在 `export/shots.json` 的逐镜 `vlm_review{}`。
* rubric 的 5 档锚点是**新写的**（TDD §5.5 只规定"1–5 分＋一句理由"）。
  它**不是** E1 那把 `RELEVANT = 4.0` 的尺，也**没有**任何门挂它。
