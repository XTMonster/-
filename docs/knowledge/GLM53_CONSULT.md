# 常驻外部顾问：GLM 5.3（智谱）多角度会诊

**用途**：遇到难处随时把**冻结的产物**交给外部模型族（智谱）按**不同角色**看一遍，
再把它的每一条断言在仓库里**证实或证伪**。它不是"权威"，是"换一双眼睛"——
这一轮三处真缺陷（单人镜头的轴侧、修复回合点不动草案工具、动作窗口重叠）
都是换角度才看见的。

## 怎么用

```
$env:GLM_API_KEY = "<key>"        # 只从环境变量读，绝不入库
python tools/glm_consult.py --roles 规格一致性,红队反方 \
    --question work/_q.md \
    --context docs/evidence/<run>/README.md \
    --context docs/knowledge/ACCEPTANCE_STATUS.md --context-tail 40000 \
    --out work/_consult/
```

* 每个角色写两份：`<role>.json`（模型原始 JSON）与 `<role>.usage.json`
  （模型回显、`usage`、耗时、`finish_reason`、逐档尝试）——后者是"确实调了
  glm-5.3、用的哪一档"的证据。
* `--dry-run` 只拼提示词、不联网（`tests/test_glm_consult.py` 用这条）。
* 角色表（`tools/glm_consult.py::ROLES`，互不重复）：
  `规格一致性` / `接口与契约` / `测试与验收` / `性能与鲁棒` / `红队反方` / `领域专家`。

## 实测的运行包线（2026-10-04，本机，**照这个用**）

| prompt 规模 | 档位 | 结果 |
|---|---|---|
| 42 token | `max` | 14.5 s，正文 33 字符，`stop` ✓ |
| ~1.7k token（`CONTEXT.md`） | `max` | ~25 min，正文正常，`stop` ✓ |
| ~1.7k token（`CONTEXT.md`） | `high` | **363.6 s**，completion 16174、reasoning 14232，`stop` ✓ |
| ~1.7k token | `max` ＋ `max_tokens=8192` | 217 s，**正文为空**（reasoning 8147、`length`）✗ |
| ~10k token（4 份产物） | `high` | >30 min 后**对端断连** ✗ |
| ~15k token（README ＋ 40k 字尾） | `high` | ~25 min 后**对端断连** ✗ |

⇒ **把 bundle 压到 ~2k token 以内、一次只问一件事**；大 bundle 先拆成几次，
或降到 `--level low`。`level=max` 只在"只有一个问题、愿意等半小时"时用。
空正文会自动降档（`max → high → low`）并逐档记进 usage——那是正常行为，不是失败。

## 纪律（比工具本身重要）

1. **模型的话不是事实**：每条 finding 都要在仓库里找到 `文件:行号` 或最小复现；
   没被证实的单独列进"未证实/已证伪"。
2. **不许拿它当验收**：它可以在质量门、判据、口径上提意见，
   但"改判据/调阈值"仍然走仓库自己的流程（ADR ＋ 测试）。
3. **不许把它当成"多跑一次就多一份证据"**：同一份 bundle 重复问只会得到
   措辞不同的同一批结论；要的是**不同角色**与**不同产物**。
4. 报告里必须带 `usage`（本次实测：`high` 档 1.7k token ≈ 6 分钟、16k completion
   token）——不然无法判断这次"会诊"值不值。
