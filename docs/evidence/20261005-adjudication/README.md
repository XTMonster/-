# 第三方裁决通道（qwen3.8-max-0902）：**免费额度已耗尽，裁决被阻塞**

日期 2026-10-05。用户指示："如果需要人工裁决，这边我想用第三方的ai进行裁决"，
并给了 DashScope 的 key（`sk-ws-…`，只存进 `HKCU\Environment\QWEN_API_KEY`，**未进仓库**）。

## 端点与型号（实测，`work/_probe_qwen_endpoint.py`／`work/_list_qwen_models.py`）

* 端点：`https://dashscope.aliyuncs.com/compatible-mode/v1`（OpenAI 兼容）✓；
* key 有**按模型的白名单**：`qwen3-max` → 403；`qwen3.7-text-rerank` → 403；
  **`qwen3.8-max-0902` 可用** ✓（`GET /models` 列 262 个，可用的那个用户已指定）。

## 已拿到的成果（在额度耗尽之前）

`qwen3.8-max-0902` 作为**重排器**（与两位评委 deepseek-chat／glm-5.3 都不同族）：
E1 **0.1927 → 0.2812**（+46%，两位评委同向），见
`docs/evidence/20261005-e1-filter/README.md` 的"补二"。那一跑里
**27/192 行重排失败**并具名降级——现在知道那就是**免费额度耗尽**（不是限流）✓。

## 现在为什么停了（证据逐字）

```
HTTP 403: {"error":{"message":"Free quota exhausted. To continue accessing the model
on a paid basis, please add funds or disable the \"use free tier only\" mode in the
management console.","type":"AllocationQuota.FreeTierOnly",
"code":"AllocationQuota.FreeTierOnly"}}
```

**用户侧要做的只有一件事**：在百炼控制台把 **"仅使用免费额度"（use free tier only）
关掉**（或充值），然后本仓的第三方裁决就能继续（`work/_adjudicate_decisions.py` 已就绪：
它把 **D13（P10 走 A/B/C）／D12（门⑦口径 A/B/C）／RK-13（升格／维持）** 三件
连同证据一起交给 `qwen3.8-max-0902`，判词落 `docs/evidence/20261005-adjudication/verdict.json`）。

## 未验证

* 关掉该开关之后，`qwen3.8-max-0902` 的**付费**额度是否够跑完整轮重排（64 次/轮）
  与三件裁决——**未测**（等开关）。
* 重排那一跑的 27 行失败若全部重试成功，E1 的上限**未测**（重排成功的那 165 行上
  E1 = 0.2970，可作下界）。
