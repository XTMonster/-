"""P14-1 语料采集与填充管线（执行文档 v1.4 §2.3c）。

七个脚本一一对应管线的一步：

    fetch.py → extract_text.py → dedupe.py → validate_licenses.py
             → chunk.py → annotate.py → import_cards.py

这一层是**开发侧**工具：只在 sidecar / 构建机上跑，不进 Blender 进程，
因此可以用 PyYAML；`block_director/` 里的任何模块都**不得**导入本包。
"""
