# 联合会诊纪要（DeepSeek × GLM-5.3）

- 模型：`deepseek-chat`（deepseek 族） × `glm-5.3`（zhipu 族）——**天然换族**
- 判词归属：`reviewed_by: llm-panel`（**不是** human，也不冒充 human）
- 输入：1 份源码、0 份产物；逐份 sha256 见 `bundle.manifest.json`
- 纪律：**一侧缺席不算同意**；会诊结论不改判据/门限/阈值。

## 角色：实现顾问

- 状态：deepseek=`main-answer`，glm=`ok`；完整=True
- usage：{"deepseek": {"model": "main-thread(deepseek)", "source": "main-answer"}, "glm": {"model": "glm-5.3", "requested_model": "glm-5.3", "level": "high", "max_tokens": 65536, "elapsed_s": 715.7, "usage": {"completion_tokens": 54200, "completion_tokens_details": {"reasoning_tokens": 48283}, "prompt_tokens": 2358, "prompt_tokens_details": {"cached_tokens": 0}, "total_tokens": 56558}, "finish_reason": "stop", "attempts": [{"model": "glm-5.3", "requested_model": "glm-5.3", "level": "high", "max_tokens": 65536, "elapsed_s": 715.7, "usage": {"completion_tokens": 54200, "completion_tokens_details": {"reasoning_tokens": 48283}, "prompt_tokens": 2358, "prompt_tokens_details": {"cached_tokens": 0}, "total_tokens": 56558}, "finish_reason": "stop"}]}}

### 两侧都提（严重度一致）（0）
（无）

### 两侧都提但**严重度不同**（0）
（无）

### 只有 GLM-5.3 提（5）
- **已入库的 0.7760 上限证书与红线不同尺，且漂移方向表明它是高估**（blocker）：0.7760 不能作为『红线 0.70 可达』的证据：其全部相关标签产自每次调用看 20 条候选的判分语境，而红线 E1 在每次调用看 3 条的语境下测量；P14-199 证明两种语境不可比且 C 越大分数越高，因此该证书相对红线尺度系统性偏乐观。同尺证书应固定 C=3、报 K。
- **判分语境被 --top-k 一个旋钮绑死；出同尺证书前必须先在面板解耦**（major）：要『固定 C=3、报 K』，前提是面板能把『每次判分调用喂几条』从 --top-k 里拆成独立参数；当前两者耦合（P14-199 只能动 --top-k 且调用规模随之 3↔20），所以任何『扩大 K』的跑都同时改了 C，量出的上限天然不同尺。e1_ceiling_report.py 本身不需要改。
- **只用现有产物定不了案；缺的量是 C=3 语境下排名 4–20 的池标签**（major）：不能。只用 K=20 的 1280 行（全部 C=20 标签）＋ K=3 的 192 行（C=3 标签、仅每查询前 3 条），无法判定『K 充分大时上限 ≥ 0.70』。缺的量：在每次判分调用 3 条的语境下、每查询候选池内两位评委均值 ≥ 4.0 的条数——对排名 4–20 的 1088 行（64×17；64 由 1280/20＝192/3 推出）这个量完全未知。
- **最小新测量：K=20 内容按 3 条一呼重判，report(rows, top_k=3) 读 ceiling**（major）：一次新判分即可定案，零新检索、e1_ceiling_report 零改动，且红线 0.70、阈值 4.0、前 3 行分母全部不动：把 K=20 跑的候选内容（excerpt 逐字节沿用）按每查询、检索序切成连续三元组（取 ranks 1–18；19–20 只能 2 条一呼、属另一种语境，不入主证书），以 batch=3、同一提示词 sha 重判，合并落盘为一个打分文件，调 report(rows, top_k=3) 读 ceiling。判据：ceiling ≥ 0.70 ⇒ 可达；ceiling < 0.70 ⇒ 该池不可达；|ceiling−0.70| ≤ 0.016 ⇒ 原样重复一次再判。
- **报告输出没有判分语境/提示词 sha 字段，尺度事后不可追溯**（minor）：report 的返回字典记录了 relevant_threshold（第 121 行）和 top_k（第 122 行），但没有『每次判分调用几条』与提示词 sha；同尺证书必须把 C 与 sha 作为一等字段落盘——这正是 Q1『报哪一个』的落点：被固定的旋钮要写进产物，否则『哪把尺子』只能靠重做配对实验才知道。

### 只有 DeepSeek 提（3）
- **K 与判分语境必须写成两个独立旋钮**（high）：上限(K, ctx)=mean(min(3, 在 K 条候选里判为相关的行数)/3)，其中“相关”由 ctx 语境下的评委给出。现有 0.7760 是 K=20、ctx=20；红线量的是 K=3、ctx=3。两者不可互换，必须同时报。
- **现有产物不能判定“大 K 时上限>=0.70”**（high）：缺的量是“在 ctx=3 语境下、对 K>3 的候选集判分后的相关行数”。K=20 的行是在 ctx=20 语境下打的分（P14-199 已证该语境会把均分抬高），所以不能拿它当 ctx=3 的上限。
- **最小新测量：扩大 K、判分语境固定在前 3 行**（high）：用 e1_panel 以 --top-k K（如 50）取候选，但判分提示词只喂前 3 行，其余 K-3 行只作为“完美重排器可挑选的池子”；再算 mean(min(3, 池中相关数)/3)。判据：存在 K 使该值>=0.70 则结构可达，否则不可达。不降线、不换分母、阈值 4.0 不动。
