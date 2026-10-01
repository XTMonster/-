# 审查：`tools/kb_fetch/find_arxiv_sources.py`（2026-10-01 夜）

**角色视角**：接口与契约 ＋ 合规（抓取纪律）。**只读审查**，未改动被审文件。
结论先行：**许可门做得对，引用与措辞有一处小偏差；但抓取纪律有一处真实的
绕行——API 发现步骤没有过项目自己的 `robots` 门，而那个主机是 `Disallow: /`。**

---

## 一、[高] API 发现步骤绕过 `fetch.py` 的 robots 门

证据（全部可在本机复跑）：

```powershell
python -c "import sys; sys.path.insert(0,'.'); from tools.kb_fetch import fetch; \
  print(fetch.robots_allows('https://export.arxiv.org/api/query?search_query=all:test', 25.0)); \
  print(fetch._http_get('https://export.arxiv.org/robots.txt', 25.0).decode())"
# -> (False, 'robots_disallow:/')
# -> User-agent: *
#    Disallow: /
```

而 `tools/kb_fetch/find_arxiv_sources.py:154-157` 的 `_get()` 是**裸 `urllib.request`**，
`search()`（同文件 `:160-175`）每个检索词都直接打 `https://export.arxiv.org/api/query`：

```python
def _get(url, timeout):
    request = urllib.request.Request(url, headers={...})   # 没有 fetch.robots_allows
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")
```

对照项目纪律：`tools/kb_fetch/fetch.py:74-95` 的 `robots_allows()` 明写
**"按 robots.txt 判定；拿不到 robots.txt 时**拒绝**（宁缺勿滥）"**，
`tools/kb_fetch/find_sources.py`（Gutenberg 版）也是从**允许的** `cache/epub/feeds/pg_catalog.csv`
拿目录、刻意不去抓被自家 robots 禁掉的 `/ebooks/search`。也就是说，**"目录/发现"这一步在
本仓库一直是过门的**，这一份新工具是唯一的例外。

**它不是不能解释**：`export.arxiv.org/api/query` 是 arXiv **专为程序化访问提供的 API**
（arXiv 文档要求请求间隔 ≥3 s，工具默认 `--interval 3.0` 也照做了），`Disallow: /`
更像是对通用爬虫写的。但本项目的口径从来不是"我觉得它其实允许"，而是 **robots 是硬门**；
而且 `arxiv.org`（网页主机）的 `robots.txt` 是 **ALLOW**，`/list/`、`/abs/`、`/pdf/` 都过门
（实测，见 `MODERN_SOURCES_PROBE_20261001.md`）。

### 两条可执行的修法（择一，都不需要改判据）

**(a) 让发现步骤也过门——用允许的 `/list/` 页代替 API**（我实测可行）：

```python
allowed, reason = fetch.robots_allows(url, timeout)   # arxiv.org/list/... -> ALLOW
if not allowed:
    raise RuntimeError(f"robots_deny:{reason}")
```

`https://arxiv.org/list/cs.CV/recent`、`/list/cs.CV/2024-01` 等都是 ALLOW、
Crawl-delay 15 s；代价是"按标题关键词筛"而不是"按摘要检索"，且每页要等 15 s。
Crawl-delay 必须**从 `fetch.crawl_delay()` 读**（`fetch.py:118-131` 就是为这个存在的），
不能再写死 3 s——现在这个 3 s 是按 arXiv 文档写的，比它网页侧 robots 要求的 15 s 更激进。

**(b) 保留 API，但把例外写成"显式、具名、有裁决"的东西**：在 docstring 与
`docs/knowledge/MODERN_SOURCES_PROBE_20261001.md` 里写明"`export.arxiv.org` 是
条目级例外，理由是它是官方程序化入口、请求间隔 ≥3 s；用户裁决见 …"，并把
`robots_allows` 的调用保留成**先问再例外**（问出来是 `robots_disallow:/` 时把它记进
候选文件的 `robots_note` 字段）——**沉默的绕行才是问题**，具名例外不是。

## 二、[中] 文件头对"候选文件已经过门"的描述过宽

`find_arxiv_sources.py:20-24` 写的是：

> "...and every candidate goes through the existing `fetch.py` robots gate plus
> `extract_text` before it is written to the candidate file."

实际顺序（`:290-311`）：`search()`（**不过门**）→ `relevant()` 关键词筛 →
`enrich_licences()`（**过 `fetch.fetch_source`，即过机器人门**，但只覆盖 `--licences` 指定的前 N 篇）
→ `accepted()` → 写 `--out`；`extract_text` **只**在 `--verify` 时对前 N 篇跑，写的是
另一个文件 `--verified-out`。

所以准确的措辞是："候选的 **abs 页**过门；**PDF 与 `extract_text`** 只在 `--verify` 时覆盖前 N 篇"。
建议按事实改字符串（一行注释的改动，不影响逻辑）。

## 三、做得对的地方（同一份文件的正面证据，避免只报坏消息）

* **许可门是机械的**，不是"读候选的人顺手判"：`LICENSE_MAP` 只收 CC-BY / CC-BY-SA /
  CC-BY-NC-SA / CC0；`by-nc-nd` 与 arXiv perpetual（`nonexclusive-distrib`）**在映射表里
  根本不存在**，`license_class()` 因此返回 `""` → 拒收（`find_arxiv_sources.py:76-88`）。
* **测试把"两处不许分叉"钉死了**：`tests/test_find_arxiv_sources.py:47-58` 逐个
  `LICENSE_MAP` 的值断言 `common.license_allowed(name)`——白名单真源仍在
  `tools/kb_fetch/common.py`，没有第二份许可判定。
* **误命中是被实测逼出来的**：arXiv 的 `abs:` 匹配是**子串**（`anime` 命中 `animals`），
  `relevant()` 因此要求整词命中 ≥2 个且标题里至少 1 个；`TOPIC_WORDS` 与
  `--terms` 的注释都记了这条（`:44-52`）。
* `--default terms` 保持 ASCII、去重有测试（`tests/…:140`）。

## 四、现状与建议

`work/modern/arxiv_candidates.json` 现在是 **`[]`**（3 字节，19:01:49）——第一次跑
`found=63 / on_topic=0`，正是"子串匹配"那次；19:02 起的第二次跑（`--per-term 25
--licences 12 --verify 4`）还没落盘。**在 §一 处置之前，这个文件里的任何候选都建议
只当"探索结果"，不要当成"已过门的来源"**；把它接进 `sources.yaml` 之前，
走一遍管线的 `fetch → extract → dedupe → validate_licenses` 四步即可拿到同样的门
（PDF 侧 `arxiv.org/pdf/...` 实测 ALLOW，15 s 间隔）。
