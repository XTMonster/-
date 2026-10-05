# GPT-6A（中转站）的**可用包线**：`reasoning_effort=max` ＋ 大包 ⇒ Cloudflare **HTTP 524**

日期 2026-10-06 07:21。这是一条**运维约束**，不是模型能力问题。

## 现象（原始留证）

第一次跑 E1 缺口的联合会诊（`work/_panel_e1gap`，bundle 31 KB ≈ **9,355 prompt token**）：

```json
领域讲解.glm.usage.json =
{"error": "ConsultFailed: 中转站没给出正文：[
  {\"error\": \"HTTP 524: ...cloudflare-5xx-errors/error-524/\", \"elapsed_s\": 127.5},
  {\"error\": \"HTTP 524: ...\", \"elapsed_s\": 256.9},
  {\"error\": \"HTTP 524: ...\", \"elapsed_s\": 388.5}]"}
```

**三次全是 524**，一次比一次久（127 / 257 / 389 s）。同一份包的 DeepSeek 侧**正常**
（`deepseek-flash`，prompt 9,355 / completion 4,251）。

## 它说明什么

* `linkai.pics` 在 **Cloudflare** 后面；524 是**边缘等不到源站**的默认超时（约 100 s）。
* `gpt-6-astra` 是"始终思考"模型，`reasoning_effort=max` 实测把 reasoning 从 40 拉到 **1,034** token
  （`work/_probe_linkai_thinking.py`）。**输入越大思考越久** ⇒ 包一大，单次生成就超过边缘超时。
* ⇒ **包线纪律（与 GLM-5.3 那条同源，但原因不同）**：GLM 是因为"思考烧完 completion 预算 ⇒ 正文空"，
  GPT-6A 是因为"思考太久 ⇒ 边缘 524"。**两者都要把 bundle 压小**（~2k token 量级），
  一次只问一件事。

## 与"思考强度拉到最大"的关系（两条一起守，不矛盾）

用户裁决"**使用 gpt6A 时思考强度拉到最大**"照旧执行（默认 `reasoning_effort=max`）；
**能拉满的前提是把问题问小**——把一个大问题拆成几个小问题分别问，而不是降思考强度。
**不许**为了绕 524 而把 `reasoning_effort` 调低（那是**静默降级**）。

## 是否可绕

**未验证**：① 换 `LINKAI_BASE_URL` 的直连域名（若有）能不能避掉 Cloudflare；
② 流式（`stream:true`）会不会让边缘不再 524（本仓客户端目前**不带流式**）。
**已确定不可行**：把包压大——见上面。

## 处置

改用**小包重问**：`--context-tail` 截短上下文 ＋ `--no-status` ＋ 只给最相关的那一段源码，
把 prompt 压到 ~1–2k token 量级再问。
