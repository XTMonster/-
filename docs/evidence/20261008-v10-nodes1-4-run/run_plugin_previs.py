"""按**插件自己的路径**跑一次白模预演（= GUI 上那个「生成白模预演」按钮）。

逐字复刻 `block_director/layer5_orchestrator/modal_operator.py::BLOCKDIRECTOR_OT_run_previs`
的 invoke → timer → 收尾导出序列，只是把"timer 每 0.1 s 推一次"换成 while 循环：

    bd_script_path / 面板字段  ->  build_run_context(context)  ->  driver.step()*  ->  export_finished_run(run)

**不走** `tools/run_headless.py`（那是插件包的 headless 入口，不是面板路径）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TAG = "BLOCKDIRECTOR_PLUGIN_RESULT"


def _fail(message: str) -> int:
    print(TAG + " " + json.dumps({"ok": False, "problems": [message]},
                                 ensure_ascii=False))
    return 1


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(prog="run_plugin_previs")
    parser.add_argument("--script", required=True)
    parser.add_argument("--sidecar-url", default="")
    parser.add_argument("--model", default="qwen3.8-max-0902")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--preset", default="")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--max-wall-minutes", type=float, default=0.0)
    parser.add_argument("--max-cost-usd", type=float, default=0.0)
    #: 单次 LLM 调用超时。面板/config 给的是 120 s；`run_headless --llm-timeout`
    #: 的说明就写着"本地大模型常需放大到 600+"，而**思考档拉满的百炼**
    #: （qwen3.8-max-0902）同一条计划调用实测会超过 120 s（第一次尝试就是
    #: `E_LLM_001 连接失败: timed out`）——那是"跑不完"，不是"跑得慢"。
    parser.add_argument("--llm-timeout", type=float, default=0.0)
    args = parser.parse_args(argv)

    import block_director

    block_director.register()            # 真实注册路径（与点按钮同一条）

    from block_director.contracts.config import AppConfig
    from block_director.contracts.enums import TransportMode
    from block_director.layer5_orchestrator import modal_operator as operator
    from block_director.layer5_orchestrator.driver import DriverLimits
    from block_director.settings import set_config

    script_path = Path(args.script)
    if not script_path.is_file():
        return _fail(f"剧本不存在：{script_path}")

    scene = bpy.context.scene
    scene.bd_script_path = str(script_path.resolve())
    scene.bd_offline = bool(args.offline)
    scene.bd_clear_scene = True
    scene.bd_provider = args.provider
    scene.bd_model = args.model
    scene.bd_max_llm_calls = 0            # 0 = 不限（真跑的调用数由 shots*8+40 兜底）
    if args.preset:
        scene.bd_preset = args.preset
    if args.max_wall_minutes:
        scene.bd_max_wall_minutes = float(args.max_wall_minutes)
    if args.max_cost_usd:
        scene.bd_max_cost_usd = float(args.max_cost_usd)

    config = AppConfig()
    if args.sidecar_url:
        config.llm.sidecar_url = args.sidecar_url
        config.llm.transport = TransportMode.SIDECAR
    limits = DriverLimits()
    if args.llm_timeout:
        config.llm.sidecar_timeout_s = float(args.llm_timeout)
        limits.llm_timeout_s = float(args.llm_timeout)
    set_config(config)

    run = operator.build_run_context(bpy.context, config=config, limits=limits)
    if not run.ok:
        return _fail("；".join(run.problems) or "build_run_context 没给出驱动")

    driver = run.driver
    started = time.time()
    while driver.step():
        pass

    state = str(getattr(driver.state, "value", driver.state))
    payload = {
        "ok": state == "DONE",
        "state": state,
        "mode": run.mode,
        "run_id": driver.audit.run_id,
        "elapsed_s": round(time.time() - started, 1),
        "snapshot": driver.snapshot(),
        "error": driver.error,
    }
    if payload["ok"]:
        try:                            # 与模态算子一样：DONE 时先导出再收尾
            payload["export"] = operator.export_finished_run(run)
        except Exception as exc:        # noqa: BLE001 - 导出失败不吞掉运行结果
            payload["export_error"] = f"{type(exc).__name__}: {exc}"
    print(TAG + " " + json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
