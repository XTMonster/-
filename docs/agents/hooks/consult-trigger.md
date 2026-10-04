## 自动会诊触发（hook 按本次请求判定，不是人工提醒）

（判定类型：`hard` ＝ 难题攻关（**方案以 GLM-5.3 侧为主**）／`review` ＝ 质量审核·对抗审查／
`idea` ＝ 想法生成·方案与取舍。判定由 hook 从你这次的请求里读，不是你手动指定。）

本次请求被判定为：**{{KIND}}**（触发词：`{{HITS}}`）。按《模型分工契约》，
这一类**不许直接开干**——先拿两侧判词，再执行。

**要跑的命令**（`--source` 换成你真正要审的文件与行段；bundle 压到 ~2k token）：

```powershell
python tools/panel_consult.py --roles {{ROLES}} `
    --question work/_q.md `
{{SOURCES}}    --context <产物，可多份> `
    --out work/_panel_{{SLUG}}/ --level low --max-tokens 32768
```

**纪律（缺一条就算没会诊）**：

1. `--source` **逐字带行号**（`文件:起-止`）；不给源码，工具会拒调用。
2. **两侧同一份包、同一个角色提示**；结果落
   `both` / `severity_conflict` / `glm_only` / `deepseek_only` **四栏**。
   **一侧缺席（空正文/超时/`unparsed`）永远不算同意**——`panel.md` 会记 `complete=false`。
3. **GLM 的判词不是验收**：不改判据 / 门限 / 阈值，也不用"再跑一次"充当新证据。
4. 判词里每条断言都要在仓库里**证实或证伪**（`文件:行号` / 命令 / 真实输出）；
   落地、跑测试、提交仍**只在主线上做**。
5. 跑完把 `<role>.{glm,deepseek}.json`、`panel.md` 与各自的 `usage` 一并留证。
6. 若 `glm` 侧 `finish_reason=length` 且正文为空：**先把 bundle 拆小再重问**，
   别把它读成"GLM 同意"。

（本段由 `inject-context.ps1` 按提示词自动触发；路由表与角色分工见
`model-routing.md`。）
