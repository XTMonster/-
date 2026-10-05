"""P7：LightRAG 真接入的 sidecar 侧（构建期 + 运行期）。

它只做**一件事**：把"案例层"建成一个可以被查询的 LightRAG 索引，并通过一个
**只绑定本机**的 HTTP 口把 top-k 的 `case_id` 交给插件进程。

可行性已实测（`docs/knowledge/UPSTREAM_LIGHTRAG.md` §五）：`lightrag-hku 1.5.7`
＋ 系统 `torch 2.5.1+cu121`（CUDA 可用）在同一个解释器里跑得通，嵌入是我们注入的
本地函数，**不需要云端 embedding、不需要 API key**。

两个部署硬要求（都踩过）：

1. `embedding_func` 必须是 `EmbeddingFunc` **实例**（上游读 `.func`）；
2. 必须设 `HF_ENDPOINT=https://hf-mirror.com`，且要在 **import transformers 之前**。
"""
