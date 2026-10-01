# 复核：arXiv 例外边界（2026-10-01 19:50，针对 `9339f1e`）

角色视角：**安全与合规**。这是 `docs/knowledge/AUDIT_ARXIV_FINDER.md`（`edb9b03`）
那条[高] 发现被修掉之后的**独立复核**——只验证修复本身，不重复原报告。

## 结论

修复**有效且边界正确**。例外被收窄到 **一个 host 的一条路径前缀**，其余一切照旧
过仓库自己的 robots 门；越界用例（同 host 其它路径、子域、端口、userinfo 伪装、
非 http(s)）全部**不放行**。

## 证据（本机可复跑）

```python
from tools.kb_fetch import find_arxiv_sources as fa
```

| 输入 | `api_exempt()` | 判定 |
|---|---|---|
| `https://export.arxiv.org/api/query?search_query=all:test` | **True** | 具名例外本身 |
| `https://export.arxiv.org/abs/2408.17424` | False | 同 host 其它路径 → 仍走 robots（该站 `Disallow: /` → 拒） |
| `https://export.arxiv.org/` | False | 同上 |
| `https://export.arxiv.org@evil.example.com/api/query` | False | **userinfo 伪装不放行**（`netloc` 必须逐字等于例外 host） |
| `https://evil.export.arxiv.org/api/query` | False | 子域不放行 |
| `https://export.arxiv.org:8443/api/query` | False | 带端口不放行 |
| `https://EXPORT.ARXIV.ORG/api/query` | True | 大小写归一后命中（正确） |
| `http://export.arxiv.org/api/query` | True | http/https 都允许（与 `fetch.ALLOWED_SCHEMES` 同口径） |
| `file:///etc/passwd/api/query` | False | 非 http(s) 不放行 |
| `https://evil.com/api/query` | False | 别的 host 不放行 |

调用点也核对过：`_get(url, gate=True)` 的第一件事就是 `_gate(url, timeout)`
（`find_arxiv_sources.py:212-213`），也就是**请求发出之前**判定；摘要页与 PDF 两条
通路仍走 `fetch.fetch_source`（robots 门 ＋ 该站 `Crawl-delay`），没有第二条旁路。

## 仍未验证 / 边界

* 例外理由里的"arXiv 官方 API 允许程序化访问"这句话**不是本仓库能验证的事实**，
  它是外部知识；仓库能做的只是把它**具名写下**（`_discovery` 写进候选文件）并
  收窄作用域——这一点已经做到。真正的合规裁决权在用户。
* `Crawl-delay` 仍然只对**网页主机**（`arxiv.org`，15 s）读取；`export.arxiv.org`
  的 robots 是 `Disallow: /`，拿不到 delay，工具用的是 arXiv 文档的 3 s 与
  15 s 的网页侧值之间的较小者。这条差异已在模块说明里写明，属**具名偏离**。
