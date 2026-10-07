# Hooks：执行角色跟随当前选择

## 用户要求与边界

用户原话：

> 不用deepseep了，就用当前模型
>
> 对应hooks也把deepseek改成当前模型吧，这个当前模型是指当前选择的模型，不固定

本次修改主线执行、第一次修复、普通子代理和语义分类调用中的固定 DeepSeek 路由。
“当前模型”指当前会话选择，不固定成此次使用的型号；普通子代理省略 `model`。
GLM 独立评审专门职责、产品内部 E1/抽取/重排模型身份、既有验收阈值不改。
此次 v1.6 并行审查使用当前模型的不同角色，不宣称跨族会诊。

## 实施与自审

1. 盘点实际生效的 `C:\Users\小皮\.codex\hooks` 和仓库副本。
2. 备份原 `.md` / `.ps1` 至
   `C:\Users\小皮\.codex\hooks-backups\20261008-current-model`。
3. 先新增 `tests/test_hook_selected_model.py`，初跑 14 条失败：
   动态路由模块不存在、注入说明仍为固定主线、脚本仍固定请求 DeepSeek。
4. `selected-model.ps1` 从事件取型号，仅使用明确指定 provider 表内的
   endpoint / wire API / credential。适配 Responses 和 Chat 两种线协议。
5. `inject-context.ps1` 接入路由模块，去除固定型号、固定 DeepSeek 地址、
   “配置中第一枚 token”查找。关闭 HTTP 自动重定向；错误日志不记录凭据或服务端正文。
6. 更新模型分工、子代理、修复阶梯、会诊、计划、复用及裁决模板；
   历史完整保存为 `model-routing-history.md`，不再每轮注入历史路由。
7. 当前模型独立审查指出两项边界，已修：
   - 事件没给有效 provider 时，不借全局默认猜测 CLI/profile 的覆盖结果。
   - 只有 Responses `completed` 或 Chat `stop` 才能产生分类判词；
     可解析但未成功结束的 JSON 不算成功。新增反例先跑出 6 条真实失败再修。
8. 保留全部旧 hooks 自检与项目测试；未关闭守卫、未修改验收阈值。

写作采用 writing-for-agents 的“现行规则与历史参考分离”：当前路由集中在
`model-routing.md`，旧实验与接入记录单独保留，避免常驻上下文中的旧型号覆盖新选择。

## 测试与真实范围

已通过：

- `python -m pytest -q tests/test_hook_selected_model.py --junitxml=docs/evidence/20261008-current-model-hooks/targeted.xml`
  → **28 passed**。包含两种协议的本地 HTTP 端到端测试：
  同一配置连续换两个事件型号，请求 body 跟随当前选择；
  provider 凭据隔离、全局配置不变、日志无凭据、未完成响应拒收。
- `powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\小皮\.codex\hooks\selftest.ps1`
  → **133 checks / 0 failures**，原断言未删改。
- `powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\小皮\.codex\hooks\dispatch-board.selftest.ps1`
  → **25 passed / 0 failed**。
- 全部 live `.ps1` 检查为 ASCII-only；源码、模板与新增测试的
  `git diff --check` 无空白错误。原始 pytest XML 失败堆栈保留 pytest 输出的行尾空格，
  未为让空白检查变绿而重写原始测试证据。

专项测试只使用合成 token 和 `127.0.0.1` 服务，没有为验收调用收费模型。
本轮 hook 常见事件可能仅有 `model`，而没有可信的有效 provider；
这种情况下**不会转发请求**，沿用既有分类器 fail-open：保留关键词分类，
记录 `semantic unavailable: effective provider missing from hook event`。
这不改变主线及普通子代理对当前模型的继承。不能将专项 HTTP 测试说成
所有账户认证方式或所有 CLI/profile 覆盖组合的线上验证。

项目全量基线不是全绿：修改 hooks 前已发现 5 项失败：

1. `test_config_vlm_review.py::test_rule_top_k_default_is_five_and_legal`
2. `test_config_vlm_review.py::test_a_config_without_the_new_keys_falls_back_to_defaults`
3. `test_golden.py::test_derived_fixtures_match_the_plan`
4. `test_needs_review.py::test_readme_has_review_section`
5. `test_needs_review.py::test_readme_omits_review_section_when_none`

前两项是已有 `rule_top_k=8` 与旧断言 `5` 冲突；第三项是本轮开始前已有 A5
`needs_review` 字段造成的 golden 漂移；后两项是已有 A5 pytest 导入 bpy。
此 hooks 子任务未改这些产品代码或旧断言。代码停止变动后的最终全量命令：

`python -m pytest --junitxml=docs/evidence/20261008-current-model-hooks/pytest-final.xml`

→ **2871 passed / 5 failed / 1 skipped，187.92 s**；五项失败与改前一致，
没有新增跳过项。结果记录于 `pytest-final.xml`；较早 `pytest.xml` 为实施期间运行，
不充当最终稳定快照。本记录不把 hooks 专项通过宣称为 v1.6 产品开发完成或全项目通过。

## 配置完整性

修改前后相同：

| 文件 | SHA256 |
| --- | --- |
| `C:\Users\小皮\.codex\config.toml` | `58E151B5D4A9CB9BF9A3F9BD6DE62D216E51F4AC3B5444D28669F3B4B94F53B7` |
| `C:\Users\小皮\.codex\hooks.json` | `6FA23FC7AEC064EC779806E852309ACE9132C383761275B41CE3ED5C4F8BCE79` |

未重启应用、未改全局 provider/型号、未修改信任设置。
可恢复原始 hooks 文件；恢复时应逐文件核对，避免覆盖之后的新改动。
