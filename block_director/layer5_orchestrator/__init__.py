"""LLM 编排层：状态机、工具、Planner（执行文档 v1.2 §2.3 / §7）。

本包的 ``driver`` / ``tool_registry`` / ``planner`` 不依赖 bpy；
只有 ``modal_operator`` 与 ``headless_runner`` 触碰 Blender。
"""
