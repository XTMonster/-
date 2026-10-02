# 真实模型运行：云端 GLM ＋ 扩大后的语料（2026-10-02 14:00）

这是**第一次**在**当前**语料上跑完整条真实通路：sidecar 接智谱 GLM，
插件侧 `--sidecar --build --export`，产出 6 镜白模预演 ＋ 交付包。
它补的是 §4.4 步骤 2 那一步——**唯一**能判 Q5／E2 的地方。

## 怎么跑的（两条命令，可复现）

```
python tools/sidecar_server.py --host 127.0.0.1 --port 8765 \
  --upstream https://open.bigmodel.cn/api/paas/v4 --upstream-kind openai \
  --model glm-4.7 --upstream-api-key-env GLM_API_KEY \
  --think off --temperature 0 --seed 0 --knowledge-dir knowledge --cases-backend hybrid

blender --background --factory-startup --python tools/run_headless.py -- \
  --sidecar --script fixtures/shotlist_market.md --build \
  --save docs/evidence/20261002_real/project \
  --export --export-dir docs/evidence/20261002_real \
  --wall 2400 --llm-timeout 300 --max-llm-calls 120
```

密钥只从环境变量读（`--upstream-api-key-env` 传的是**变量名**，不是密钥）。

**第一次跑（`blender.log`）用了默认的 `--wall 180`，超时终止**——38 次调用里
每次要几十秒，180 秒只够跑到计划阶段。这条写在这里是因为它是**一条真缺陷的现场**：
文档 §4.4 步骤 2 没写墙上时间预算，照字面跑会得到 `state=ERROR / 超出墙上时间上限`，
而那不是模型失败。第二次给到 2400 秒就一路 DONE。

## 结果（第二次：`blender2.log`）

```
BLOCKDIRECTOR_SAVED   project/project.bdproj
BLOCKDIRECTOR_EXPORT  ok=true / 17 个交付文件
BLOCKDIRECTOR_RESULT  state=DONE / 6 镜 / 792 帧 / built=true
                      llm_calls=38 / retrieval_calls=7（hypergraph，未降级）
                      movements=2 / vfx=2 / crowd=30 / keyframes=360
                      audit_pass_rate = 4/5
                      script_compliance ok=true，两条 warning：
                        R014 shot_005 声明 follow_subject 但偷盗者没走位
                        R015 镜号3 剧本声明 MCU、计划给 MS
```

`knowledge_trace.json`：`backend=hypergraph`、`cards=2130`、`lanes=2`、
`retrieval_calls=7`、`seeds=3`、`expanded_edges=40`、`selected` 5 条边。
也就是说**扩大后的语料与索引真的被消费了**，而且是超图通道、没有降级。

`knowledge_provenance` 里**每一镜**都有 `experience`（L2 经验层）桶，例如
`shot_003`: `[[intent,推进],[shot_size,MCU],[movement,dolly_in],[lens,85mm],
[headroom_policy,cinematic]]`。这是 L2 经验层第一次真的参与一次成片。

## 这次运行**没能**判掉的两件事（照实记）

1. **E2 仍是 0/6，而且原因不是"经验没被用"。** `quality.py::e2_adoption()` 读的是
   `shots.json.movements[].source`，而 `manifest.py:184-207` 的规则是
   "**只要这条运镜等于计划自己声明的那个，就记 `declared`**"——这一轮 6 镜的运镜
   全是计划声明的，于是分子 0。按 §2.3b 的**另一半**判据（"且命中人工期望"），
   E2 还需要 `expect_movements`，而那正是 Q5 缺的那个字段。所以 E2 现在有两个
   独立的零：一个是"没被采纳为知识来源"，一个是"没有可对拍的人工期望"。
2. **Q5 仍是 `not_measured`**：夹具里带 `expect_movements` 的条目 **0 < 30**。
   这一轮有了真实的逐镜产物，缺的只剩夹具侧的独立标注——§4.1b 第一步。

## 另外两条被这次运行照出来的东西

* **L3 案例栏是活的，但 `BLOCKDIRECTOR_RESULT.knowledge.cases` 只报"最后一次调用"的数。**
  交付包里那份摘要是 `cases: 0`，看单条摘要会误判成"案例层没接线"。
  按 `audit_log.jsonl` 的 10 条 `retrieval_call` 逐条数：

  ```
  cases 分布：3 条案例 × 5 次调用，0 条 × 5 次
  逐镜查询（如 `景别=CU；运镜=dolly_in；对白=dialogue`）拿到 3 条案例；
  只写 `景别=MCU` 这种单键查询拿 0 条 —— 案例层是 BM25/向量，键太少就召不回。
  ```

  所以"第三栏是空的"只发生在**查询太短**的那些镜头上，不是接线问题。
  这也解释了为什么第一轮那次摘要里是 3、这一轮是 0：两次的**最后一次调用**不同。
* `audit_log.jsonl` 里 `run_failed: 1`——那是**第一次超时那次**留下的，两次运行
  写在同一个 `runs/` 目录里。读这份日志时要按 `run_id` 分组。
