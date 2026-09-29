# ADR-0009 SDL 文件格式升 1.4（含 `with_labels`），包/协议版本不动

状态：Accepted（v1.4 / P9.4）

## 背景

- v1.3 的 `SDLScene` 里**没有** `with_labels` 字段，`sdl_to_spec` 也不写回，
  于是"用户关掉标签 → 保存 → 重新打开"会把关闭状态丢掉。
- 仓库里同时存在两套版本号：**包/协议版本**（`block_director.__version__`、
  `CONTRACT_VERSION`、`pyproject.toml`、`blender_manifest.toml`、
  `specs/openapi.yaml`）与 **SDL 文件格式版本**（`contracts/sdl.py`）。

## 决策

- **SDL 文件格式**升到 `1.4`：`SDLProject.with_labels` 落盘、`build_sdl` 写入、
  `sdl_to_spec` 读回；`sdl_migrate.KNOWN_VERSIONS` 补 `"1.3"`，
  1.3 及更早的文件迁移后 `with_labels` 取默认 `True`。
- **包/协议版本保持 `1.3.0` 不动**。两套版本互相独立，同批修改会让下游
  消费者（含 `tests/test_package_surface.py`）误判。

## 后果

- 版本串的回归面（`tests/test_sdl.py`、`tests/test_project_io.py`、
  `tools/blender_tests/test_layer2_project.py`、`test_ui_panels.py`）改成
  `== SDL_VERSION` 而不是硬写 `"1.3"`，`fixtures/expected_sdl_simple.json`
  由 `python tools/gen_golden.py` 重新生成。
- 新增 `tests/test_sdl_labels.py` 钉住"保存 → 加载 → 重建"的往返。
- **被否决的替代方案**：用 `dataclasses.replace` 在 `sdl_to_spec` 里重建
  `SceneSpec`——那只改读回侧，值**从来没有落过盘**，关了再开依旧是 `True`。
