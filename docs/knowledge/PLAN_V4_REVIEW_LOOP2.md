# 联合会诊纪要（DeepSeek × GLM-5.3）

- 模型：`deepseek-chat`（deepseek 族） × `glm-5.3`（zhipu 族）——**天然换族**
- 判词归属：`reviewed_by: llm-panel`（**不是** human，也不冒充 human）
- 输入：1 份源码、1 份产物；逐份 sha256 见 `bundle.manifest.json`
- 纪律：**一侧缺席不算同意**；会诊结论不改判据/门限/阈值。

## 角色：红队反方

- 状态：deepseek=`ok`，glm=`ok`；完整=True
- usage：{"deepseek": {"model": "deepseek-flash", "requested_model": "deepseek-chat", "usage": {"prompt_tokens": 2796, "completion_tokens": 5086}}, "glm": {"model": "glm-5.3", "requested_model": "glm-5.3", "level": "low", "max_tokens": 65536, "elapsed_s": 366.3, "usage": {"completion_tokens": 34648, "completion_tokens_details": {"reasoning_tokens": 27044}, "prompt_tokens": 2778, "prompt_tokens_details": {"cached_tokens": 0}, "total_tokens": 37426}, "finish_reason": "stop", "attempts": [{"model": "glm-5.3", "requested_model": "glm-5.3", "level": "low", "max_tokens": 65536, "elapsed_s": 366.3, "usage": {"completion_tokens": 34648, "completion_tokens_details": {"reasoning_tokens": 27044}, "prompt_tokens": 2778, "prompt_tokens_details": {"cached_tokens": 0}, "total_tokens": 37426}, "finish_reason": "stop"}]}}

### 两侧都提（严重度一致）（0）
（无）

### 两侧都提但**严重度不同**（0）
（无）

### 只有 GLM-5.3 提（10）
- **C6 的 0.02 显著性线被它自己报告的数据击穿**（blocker）：C6 的判读规则（|ΔE1| < 0.02 标 inconclusive）与其自报读数自相矛盾：hybrid 臂两次相差 4/192=0.02083、lexical 臂极差 7/192=0.03646，两者都 ≥ 0.02。把同一配置的两次运行当作假想 A/B 臂输入这条规则，输出会是'有效差异'——而那纯属评委噪声。
- **红线 E1 ≥ 0.70 的可达性与验收时点双缺失**（major）：现有基线（同一份索引、192 行）hybrid 0.1823–0.2031、lexical 0.1927–0.2292，红线要求 top-1 ≥ 0.70，是 3 倍以上的跳变；包内没有任何新语料试点，没有写明 0.70 在 P0–P11 哪个阶段、用哪条命令验收，且两个上游 D1（语料清单）与 D3（embedding）均为未决。
- **检查器零改动 × 影子路径：切换前新产物可能不在检查器视野内**（major）：C5③ 承诺 E3 检查器零改动，C7 把新产物放 knowledge_v4/、旧 knowledge/ 逐字节冻结到 P10——若检查器（及 E1 面板）读取的目录是硬编码的 knowledge/，则 P10 切换前 knowledge_v4/ 的任何 E3/E1 读数要么做不出来、要么实际测的是旧产物。两个主张合起来把新产物的检验窗口锁死到切换瞬间。
- **"只用检索端"与"配 llm_model_func"不能同时字面为真**（major）：C3 声称只用 LightRAG 检索端（mode="hybrid"）、不用生成端；C11 又把 "LightRAG 的 llm_model_func" 列为要改成 DeepSeek 的内部 LLM。配置 llm_model_func 只有在检索路径会调用 LLM 时才有意义：要么检索端无 LLM（C11 该项为空操作），要么 hybrid 检索内嵌 LLM 生成（C5① 的'无自由生成文本'措辞失准，且 C6 的噪声模型漏了一个噪声源）。
- **sidecar 手抄漂移有前科；双端记录与降级混流未设防**（major）：本仓提交 53d3e3f 的标题原文承认"sidecar 手抄的那份已经漂了"——'sidecar 与插件各自记一份'的架构在本项目已产生过真实漂移。C3 仍采用 sidecar 独立进程＋插件经 http://127.0.0.1:8765 的双端架构，而 C7 的 sha256 只锁旧 knowledge/ 五件产物，C9 的负例清单没有'降级发生必须显式标注'，C6 的成对纪律没有把'降级计数=0'列为有效轮次前提。
- **C8 '主产物零违例'是构造性结果；0.30 门无基线校准**（major）："主产物零违例（违例全在 hypergraph.rejects.jsonl）"不是质量测量而是流程定义——主产物正是'闭集过滤后剩下的部分'，违例当然全在 rejects；真正的质量指标只有 rejects 率，而 ≤0.30 这个门在包内没有任何旧语料基线数字支撑，且 0.30 意味着丢弃近三分之一记录仍算通过。
- **E1 评委独立性无机制保障，D4 一换就变自我评分**（major）：C11 只承诺评委'不因 U10 而改'，但 D4（'E1 评委是否换 DeepSeek'）是独立未决项——若 D4 裁决换 DeepSeek，而抽取 LLM 已是 DeepSeek，红线 E1 0.70 就变成'DeepSeek 评 DeepSeek 抽的产物'。包内未披露 DEFAULT_PANEL 的评委模型，当前是否已同源无法确认。
- **C2 的参考价值空转：参考库没有研究目标所需的结构**（minor）：C2 自述 HyperGraphRAG "无 type/role/kind/槽位"，而 U7 的研究目标是"白模预演强耦合（行为/动作/情绪/意图 × 镜头语言 × 构图 × 震动打击感）"——取的三点（两趟'分段→归属'、completeness_score→confidence、每条记录带分）全是工程流程，没有一个触及多轴结构表达；且'实测'未给仓库版本与命令，不可复现。
- **C9 的 ΔE1=0.01 负例不可确定性构造；C12 把阶段门窄化为 pytest**（minor）：C9 四条负例中"ΔE1=0.01 必须被标 inconclusive"依赖真实评委恰好打出 0.01 的差——不可控、不可重复，作为回归负例无效。C12 对每阶段的机械承诺只有 "python -m pytest -q 必须全绿"，红线 E1/E3 的验收命令未出现在该承诺里（阶段表正文不在本包，无法确认是否别处写死）。
- **"保留检索契约签名"可能与"真接入 LightRAG"目标冲突**（minor）：C1 保留检索契约签名（接口冻结），U5 要求"真接入 LightRAG"——若 LightRAG hybrid 检索的返回语义（超图多跳、来源结构）在旧签名里无字段可放，接入会被接口裁剪成'另一个排序器'，'真接入'名存实亡。契约签名的字段定义不在本包，冲突是否真实存在不可判定。

### 只有 DeepSeek 提（7）
- **C1 把 E1 的分子定义划进'仪器'，是循环论证**（blocker）：C1 声称保留'判据执行环境＝E1 面板与 E3 检查器与门①–⑩'，理由是'换掉它们等于放弃研究课题本身'。但 E1 的分子是'两位 LLM 评委 1–5 分均值 ≥ 4.0 的行数'（C6 原文），这个定义直接决定了什么算'好'，它本身就是被测件的一部分，不是中立的仪器。
- **C6 的数据证明 E1 在两条路之间没有分辨力，但结论只写了'标 inconclusive'**（blocker）：C6 列出 hybrid 35/192=0.1823、39/192=0.2031；lexical 41/192=0.2135、37/192=0.1927、44/192=0.2292，然后说'两条路的大小关系会翻转'，结论是'|ΔE1| < 0.02 标 inconclusive'。但按这些数字，hybrid 的均值约 0.193，lexical 的均值约 0.212，差约 0.019——正好落在 0.02 阈值以下。也就是说，按 C6 自己的规则，这两条路的比较**永远**是 inconclusive。
- **C2 的'零拷贝'是对某一版实现的观察，不是对算法类的结论**（major）：C2 说 HyperGraphRAG 的'超边'＝一句话＋0–10 完整度分，无 type/role/kind/槽位，成员按记录流挂'最近一句'，然后结论是'取其三点……不拷任何代码'。但'无 type/role/kind/槽位'是对**某一版** HyperGraphRAG 实现的观察，不是对'超图 RAG'这个算法类的结论。
- **C4 把'本 key 无资源包'说成'物理上没有 embedding 端点'**（major）：C4 说'实测 DeepSeek /v1/embeddings、/embeddings、/beta/embeddings 全 404、GET /models 405，物理上没有 embedding 端点'。404 和 405 是对**当前 key 和当前 API 版本**的响应，不是对'DeepSeek 没有 embedding 能力'的证明。
- **C8 的 0.30 阈值没有分母定义**（major）：C8 说'rejects 率超 0.30 即停并提请裁决'，但没有定义 rejects 率的分母是什么。是抽取出的记录总数，还是输入句子总数，还是别的？
- **C12 的'每阶段 pytest 全绿'在 D1 未决时不可执行**（major）：C12 说'每个阶段退出时 python -m pytest -q 必须全绿'，但 D1（新语料来源与书单）是'当前最大开口：还没有可抓来源的实测清单'。如果语料还没确定，P0 之后的阶段无法真正执行。
- **C3 的'只用检索端'没有说明 LightRAG 的检索端是否真的不触发生成**（minor）：C3 说'只用检索端（mode="hybrid"），不用生成端'，C5 说'只用检索端、无自由生成文本进下游'。但 LightRAG 的 hybrid 模式在检索时是否内部调用了 LLM（如 query 改写、关键词抽取），计划没有说明。

## 角色：测试与验收

- 状态：deepseek=`ok`，glm=`ok`；完整=True
- usage：{"deepseek": {"model": "deepseek-flash", "requested_model": "deepseek-chat", "usage": {"prompt_tokens": 2783, "completion_tokens": 6875}}, "glm": {"model": "glm-5.3", "requested_model": "glm-5.3", "level": "low", "max_tokens": 65536, "elapsed_s": 502.5, "usage": {"completion_tokens": 40604, "completion_tokens_details": {"reasoning_tokens": 34037}, "prompt_tokens": 2766, "prompt_tokens_details": {"cached_tokens": 0}, "total_tokens": 43370}, "finish_reason": "stop", "attempts": [{"model": "glm-5.3", "requested_model": "glm-5.3", "level": "low", "max_tokens": 65536, "elapsed_s": 502.5, "usage": {"completion_tokens": 40604, "completion_tokens_details": {"reasoning_tokens": 34037}, "prompt_tokens": 2766, "prompt_tokens_details": {"cached_tokens": 0}, "total_tokens": 43370}, "finish_reason": "stop"}]}}

### 两侧都提（严重度一致）（0）
（无）

### 两侧都提但**严重度不同**（0）
（无）

### 只有 GLM-5.3 提（8）
- **C6 噪声带自相矛盾（极差写成 ±），且 0.02 阈值低于自己量到的同臂极差**（major）：C6 的读数纪律撑不起'两臂差异可判定'：'极差最大 7 行'与'±0.036'是两个不同的量（7/192=0.0365 是全距；±0.036 意味着半宽 0.036、带宽 14 行）；同臂实测极差 0.0365 大于 inconclusive 阈值 0.02；正文说'四次实测'却列了五个数（hybrid 仅 2 跑、lexical 至少 3 跑），且'≥2 次'未写两次配对是否必须同号。
- **E1 的分母（192 行）在'完全重建'后的迁移规则未声明——红线 0.70 可能失去对照**（major）：C1 的保留清单不含评测行集，C6 的噪声带是在旧索引＋旧 192 行上测的；重建后行集换不换、若换则 0.02 的标定是否在新行集上重测，两条都没写——现有证据下不可判定，且'换一套好评的行'是把 E1 做绿的最直接路径。
- **C8 的'rejects 率 ≤ 0.30'缺分母定义与基线数——停机规则当前不可执行**（major）：'rejects 率超 0.30 即停'这条写死的停机规则缺两样东西：分母公式（rejects 除以什么）与首跑基线值；按现有文本，无法用一条命令算出这个率。
- **E3 键集双源（cases.py 与 quality.py）且无可见同步断言——E3=0 存在假绿通道**（major）：E3 违例键在 cases.py:42（CONSTRAINT_KEYS）与 tools/knowledge/quality.py::e3_cases 各有一份，靠注释对齐而非机制对齐；若检查器一侧扫得比文档窄，E3 照报 0 而违例照过。C5 承诺'检查器零改动'，恰好把这种漂移风险一并冻结。
- **C4 '物理上没有 embedding 端点'是单轮无对照探测——结论强度超过证据强度**（major）：四条探测结果（三个 404＋一个 405）都是单次、无阳性对照、无回包存档；'物理上没有'是全称否定，需要可复现的探测记录加一个证明探测方法本身有效的对照，包内两者皆无。
- **C3 的接入细节全部无冒烟证据，且插件/sidecar 边界已有漂移前科**（major）：lightrag-hku 能否装进系统 Python 3.10.11、起在 8765、以 mode="hybrid" 返回契约字段——包内没有任何一次成功往返的记录；同时 53d3e3f 证明这条边界上的手抄副本会漂，而 C3/C10 没有为新 HTTP 线协议安排单一事实源。
- **C7 的'五件产物'没有枚举清单——sha256 审计面不完整**（minor）：C7 说旧 knowledge/ 五件产物逐字节不动，但本包能见到的 knowledge/ 产物文件名只有两个（cases.py:44-45 的 cases.jsonl 与 cases.manifest.json）；未列名的产物比对不到，清单本身也不在哈希范围内；hypergraph.rejects.jsonl 属于旧五件还是新产物亦未说明。
- **C2 对 HyperGraphRAG 的'实测'没有存档产物——单次、不可复验**（minor）：'超边＝一句话＋0–10 完整度分''成员挂最近一句'是对外部系统行为的实证断言，包内没有脚本、输出样本、版本号或存档路径；作为 C2 三点取舍（两趟分段→归属、completeness_score→confidence、每条记录带分）的依据，它是单次未存档观察。

### 只有 DeepSeek 提（12）
- **C6 的 inconclusive 阈值 0.02 小于它自己量出的噪声极差 0.036**（blocker）：C6 主张 |ΔE1| < 0.02 标 inconclusive，但它同一段给出的同臂极差是 7 行（±0.036）。阈值比噪声带宽还小，这个阈值不是从数据推出的，按它执行会把噪声当信号、或把信号当噪声，两种错都会发生。
- **C8 的 rejects 率 ≤ 0.30 没有分母定义、没有来源**（blocker）：C8 主张'闭集违例＝0 ＋ rejects 率 ≤ 0.30 就停'，但包内没有任何地方定义 rejects 率的分母（是全部抽取记录？全部候选超边？全部案例行？），也没有说明 0.30 从哪来。没有分母的比率不可判定。
- **C4 的'物理上没有 embedding 端点'是单 key 单时刻探测的过强措辞**（major）：C4 从'DeepSeek /v1/embeddings、/embeddings、/beta/embeddings 全 404、GET /models 405'推出'物理上没有 embedding 端点'。这是本 key 在某一时刻对三个路径的探测结果，不能升格为'物理上没有'。
- **C6 的'两条路的大小关系会翻转'是四次单跑，不是成对复验**（major）：C6 用 hybrid 35/39 与 lexical 41/37/44 这几次单跑推出'两条路的大小关系会翻转'。这些是各自独立的单跑，不是同一条件下的成对复验，不能支撑'翻转'这个结论。
- **C9 的负例是'举例'，不是已执行的负例测试**（major）：C9 主张'新增判据必须有负例'，并列了四个对抗性用例，但包内没有任何证据表明这四个负例已经被执行过、或已经挂进测试。它是一条要求，不是一条已验证的事实。
- **C1 的'保留 3 项'没有对照：换掉它们会怎样，包内无证据**（major）：C1 主张保留判据执行环境、槽位闭集表示层、检索契约签名，理由是'换掉它们等于放弃研究课题本身'。这是一个论证，不是一个可验证的结论；包内没有'换掉后 E1/E3 会怎样'的对照。
- **C2 的'零拷贝'与'不拷任何代码'是意图声明，不是可验证事实**（major）：C2 主张 HyperGraphRAG 只作算法参考、零拷贝、不拷任何代码，并列出取其三点的具体内容。但包内没有给出 HyperGraphRAG 的版本、commit、或'本仓无其代码'的扫描结果。'零拷贝'目前不可验证。
- **C3 的'真接入'没有端到端证据：sidecar 与插件进程的连通性未验**（major）：C3 主张 LightRAG 真接入＝依赖级接入、住 sidecar、插件进程经 urllib 走 127.0.0.1:8765、只用检索端。包内没有 sidecar 启动、端口监听、或一次成功检索的记录。'真接入'目前是设计，不是事实。
- **C7 的'逐字节不动'与'每阶段 sha256 前后比对'没有给出比对对象清单**（minor）：C7 主张旧 knowledge/ 五件产物在切换前逐字节不动、每阶段用 sha256 前后比对证明。但包内没有列出这五件产物是哪五件，也没有给基线 sha256。'五件'与'逐字节不动'目前无法复算。
- **C10 的'新增依赖＝0'没有给出 import 白名单的当前内容**（minor）：C10 主张插件进程新增依赖＝0，用 import 白名单测试机制化断言。但包内没有给出当前白名单，也没有给出测试文件位置。'新增＝0'需要一个基线白名单才能判定。
- **C11 的'不因它而改'没有对照：U10 改与不改，E1 读数是否变**（minor）：C11 主张 U10 只改'用别人方案'处的内部 LLM，本仓自有仪器（E1 评委 DEFAULT_PANEL）与计划起草/审查通道不因它而改。这是一个边界声明，包内没有'改与不改 E1 读数是否变'的对照。
- **C12 的'pytest -q 必须全绿'没有给出当前基线是否全绿**（minor）：C12 主张每阶段退出时 python -m pytest -q 必须全绿。但包内没有给出当前 HEAD 上 pytest -q 的结果。如果当前就不是全绿，这条 DoD 无法作为阶段门。
