# v1.7 H3 收尾证据（2026-10-17）

## 环境

- OS：Windows（Asia/Shanghai，cp936 控制台，探测时按 UTF-8 处理）
- Blender：5.2.0 LTS（hash `fbe6228777e7`，built 2026-07-14）
- Python：系统 python（`python -m pytest`）
- HEAD：`d3025db`（v1.7 J4）
- 工作区状态：除隔壁窗口的空间尺转正改动（`script_parser.py`、
  `shotlist.py`、`driver.py`、`sidecar_server.py`、
  `tools/spatial_ruler_ab/llm.py`）外无 v1.7 未提交改动；本目录为新增证据。

## ① offline 全链（Web 关了也通，R-UI-2）

命令：

```powershell
blender --background --factory-startup --python tools/run_headless.py -- `
  --offline --script fixtures/script_long_61.md --build --export --preset fhd16x9 `
  --out docs/evidence/20261017-v17-h3/offline_long
```

结果：`BLOCKDIRECTOR_RESULT` `success=true`、`built=true`、
`state=DONE`、`shots=64`、`total_frames=4584`、`llm_calls=139`（上限
`max(200, 64*8+40)=552`，未触顶）；导出 `export/` 下 64 个
`blockout_shot_*.mp4` ＋ `blockout_full.mp4` ＋ `shots.json` ＋
`prompts.md` ＋ `README.md`。交付分辨率 1920x1080（与 run_tests.ps1
step1 的 `--preset fhd16x9` 断言同源）。本次跑法与
`tools/run_tests.ps1` step 4 同款命令（`--offline --build --export
--preset fhd16x9`），golden 确定性对拍由 `tests/test_golden.py`
（9 passed）与 `gen_golden.py --check` 覆盖。

## ② sidecar＋Web＋3 镜样例

- 起真实 sidecar（`--web-root web/`、`--token bd-h3-smoke-token`），
  探测 13 个端点并落 `sidecar_web_smoke.json`（脚本
  `sidecar_web_smoke.py`）：**overall PASS**——静态 `/`、
  `/static/app.js`、`/static/polish.js`、`/static/pixel.css` 200；
  无 token 访问 `/v1/ui/*` 401；带 token 的 rules/events/config/
  state_map/knowledge.stats 全 200 且形状正确；polish 无上游时 502
  结构化 error（E2 良定义）；polish/accept 空 run_id 400。
- 3 镜样例导出：`sample3/project/export/`（13 镜全渲染）＋
  `sample3/reference_pack/` 五件套清单：

| 文件 | 说明 |
|---|---|
| README.md | reference_pack 说明（目标模型/工程/对拍字段） |
| prompt_seedance_2.5.txt | 视频生成提示词种子模板 |
| shot_cards.md | 逐镜卡（角色/景别/运镜/时长） |
| continuity.json | 连续性快照（axis/屏幕方向/景别/视线） |
| responsibility.md | 分工声明（white_model 角色/动画通道） |

## ③ J 阶段冻结基线汇总

`baselines/baseline_{market4,market13,long61}.json` ＋
`baselines/baseline_summary.md`。三份工程（6/13/64 镜）逐镜
`BpyShotAuditor().audit()` 统计 R020–R025：long61 的 R020=28
（角色世界高度漂移），其余规则本批工程零触发。只记录不判红，
阈值未改。

## ④ pytest 全量

```text
4099 passed, 2 skipped in 204.54s (0:03:24)
```

（2 skipped 为既有条件守卫，非绕过判据。）

## ⑤ 协作记录

`PROGRESS.md` 全文归档见 `PROGRESS_ARCHIVE.md`（2026-10-17 快照）。
