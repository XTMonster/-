# ADR-0011 两个标签开关各有生效域

状态：Accepted（v1.4 / P12）

## 背景

仓库里有两个看着都像"标签开关"的配置：

- `character.label_render`（默认 True）——"标签是否进参考视频"；
- `ui.show_labels`（默认 True）——面板上的"显示标签"。

v1.3 的 `shot_builder` 只在 `label_render=False` 的 `else` 分支里读
`ui.show_labels`，而默认 `label_render=True` —— 于是这个开关**完全无效**；
`cast_editor.add_cast_member` 更是不读它。`character_label.py:106` 的注释
还写着"`ui.show_labels` 在 v1.2 里没有任何消费者"。

## 决策

把**生效域**写死，两边各归各位：

- `character.label_render = True` → 走**渲染路径** `create_render_label`：
  两个对象 `BD_Label_<char_id>_Fill` / `_Stroke` 进 `BlockDirector/Labels`，
  `hide_render = False`（**要**进参考视频）；
- `label_render = False` → 走 **Guides 路径** `create_label`：
  `hide_render = True`，而 `ui.show_labels` **只**控制它的 `hide_viewport`；
- `cast_editor` 新增角色时同样透传 `ui.show_labels`（X11 的"半接线"）。

## 后果

- `tools/blender_tests/test_label_toggles.py` 把四种组合逐一钉住，
  并断言"`label_render=True` 时 `ui.show_labels` 不影响渲染标签"。
- 标签是否入片的判据从"看注释"变成"看集合 + 命名 + `hide_render`"，
  与白名单（`collection_router.audit_renderable_objects`）一致。
- **被否决的替代方案**：把两个开关合并成一个——`label_render` 要进成片、
  `ui.show_labels` 只影响视口，合并后就再也无法"出片不带字、做片时可见"。
