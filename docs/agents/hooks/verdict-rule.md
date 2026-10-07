## 人工裁决触发（hook 按本次请求判定，不是人工提醒）

（判定类型：`verdict` ＝ **人工裁决**——用户 2026-10-06 把"代替我做人工审核判断"这件事
授权给了第三方裁定通道。触发词命中：`{{HITS}}`。）

**独立裁决默认走 GLM-5.3**，遵循 `model-routing.md` 的现行专门职责；
主线核对与执行使用**当前会话选择的模型（不固定）**。旧的 GPT-6A / DeepSeek
分工只属历史，不覆盖本轮选择。做法：

```powershell
python tools/holdout_review_third_party.py --entries <oracle.jsonl> `
    --out work/holdout_third_party.reviewed.jsonl `
    --report work/holdout_third_party.json --sheet work/holdout_third_party_disagreements.md `
    --provider glm --model glm-5.3 --concurrency 3
```

**判词纪律（缺一条就算没做完）**：

1. 记录一律写 `reviewed_by: "third-party"` ＋ `source{model, prompt_sha256, authorized_by}`
   —— **绝不冒充 `human`**；门⑦ 要不要把它算进"已裁"由显式 `--reviewer-classes` 决定。
2. **判据一个字不许动**（阈值 / 门限 / 分母 / 口径）。判词是**辅助证据**，不是验收。
3. 通道不可用如实报告，不自动另选固定型号。换了通道就要在记录里换型号，
   **不许**把两个通道的记录混进同一份“谁的判词”里。
4. 与既有 `llm-panel` 记录**逐条对拍**，分歧单独成表（`--sheet`）——人只需看那一份。
5. 结论交给主线执行：落地、跑测试、提交**只在主线**做。

（本段由 `inject-context.ps1` 按提示词自动触发；通道细节见 `model-routing.md` §2c。）
