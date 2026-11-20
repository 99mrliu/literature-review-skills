# rubric.json 语义说明（评分卡）

本文件定义 `rubric.json`（由 `prepare.py` 写入工作目录的默认评分卡）的
每个字段、打分规则、默认权重及理由。脚本 `rank_engine.py` 是该评分卡的
唯一解释者；模型不手算任何分数。修改评分卡 = 修改此文件后重跑
score/sensitivity/assemble，修改本身应记入 `change_log`。

## 信号定义与打分规则

### S1_topic（默认权重 0.30）

- 定义：研究主题词（`topic_terms`）命中程度，**标题权重 > 摘要权重**。
- 规则：`S1 = title_weight × (标题命中词数/词表大小) + (1−title_weight) ×
  (摘要命中词数/词表大小)`，`title_weight` 默认 0.7。无摘要时摘要覆盖率
  按 0 计（即 S1 上限降为 0.7，已在分数中体现，不另行惩罚）。
- 理由：主题相关性是排序的第一驱动，给最大权重；标题命中比摘要命中更
  强地预示主题聚焦，故标题权重更高。
- 匹配方式：ASCII 词按字母数字边界匹配（避免 `rct` 误中单词内部），
  非 ASCII（如中文）按大小写不敏感子串匹配；同一词多次出现只计一次。

### S2_population（默认权重 0.20）

- 定义：对象/人群词（`population_terms`）在标题+摘要合并文本中的覆盖率。
- 理由：研究对象不符是仅次于主题的最常见不相关原因，权重次之。
- 词表为空 → 信号"不适用"，权重按比例再分配到其余可用信号（不是 0 分）。

### S3_method（默认权重 0.15）

- 定义：方法/设计词（`method_terms`）覆盖率，规则同 S2。
- 理由：方法匹配重要但弱于主题与人群；摘要中方法描述常有缺省，给中等
  权重避免过度惩罚描述简略的真实相关文献。

### S4_evidence_level（默认权重 0.15）

- 定义：证据层级分。先在标题+摘要中按下列顺序检出研究设计（**首个命中
  即定级**，避免 `review` 吞掉 `systematic review`），再在 venue 中做
  预印本启发（arXiv、bioRxiv、medRxiv、SSRN、Research Square、
  preprints.org 等）；皆无 → `unknown`。
- 默认偏好序与得分（得分 = (n − 序位 + 1) / n，n 为偏好表长度）：

  | 序位 | 层级 | 检出关键词示例 | 默认得分 |
  |---|---|---|---|
  | 1 | meta_analysis | meta-analysis, pooled analysis | 1.000 |
  | 2 | rct | randomized controlled trial, RCT, double-blind, placebo-/sham-controlled, randomly assigned | 0.889 |
  | 3 | systematic_review | systematic review, PRISMA | 0.778 |
  | 4 | cohort | cohort, prospective study, longitudinal | 0.667 |
  | 5 | case_control | case-control | 0.556 |
  | 6 | cross_sectional | cross-sectional | 0.444 |
  | 7 | review | (narrative/scoping/…) review | 0.333 |
  | 8 | preprint | preprint 关键词或预印本 venue | 0.222 |
  | 9 | unknown | 无线索 | 0.111 |

- `criteria_terms.json` 的 `evidence_level_preference` 可重排此表以表达
  研究问题偏好（如方法学综述类问题可把 systematic_review 提前）；
  `unknown` 不在表内时按末位计分。层级只降权不硬排除：预印本仍可凭高
  主题分进入 pending。

### S5_recency（默认权重 0.10）

- 定义：时间窗新近度。参考年 = 候选集中最大出版年（确定性，不取当前
  系统时间，保证可复现）；年龄 ≤ `recency_years`（默认 10，可被
  criteria_terms 覆盖）→ 1.0；超出后线性衰减，年龄 ≥ 2×窗口 → 0.0。
- 缺年份 → 信号"不可用"，权重再分配，且该条进 metadata_gaps。
- 理由：新近性加分但不应压过内容与证据层级，故权重最低档。

### S6_metadata（默认权重 0.10）

- 定义：元数据完整度/来源质量 = 六字段加权占比：title 0.25、abstract
  0.30、year 0.15、authors 0.10、venue 0.10、doi 0.10。
- 理由：元数据完整的记录其排序依据更可核验；权重最低档，仅作质量微调，
  不让"字段齐"压过"内容相关"。

## 融合与不可用信号

总分 = Σ(权重×信号分) / Σ(可用信号权重)。不可用（不适用/缺数据）信号
的权重按比例再分配给其余可用信号，每条记录的 `applied_weights` 记录了
实际使用的归一化权重，保证可复算。

## 阈值与标签

- `thresholds.retained`（默认 0.65）、`thresholds.pending`（默认 0.40）：
  总分 ≥ retained → retained；∈ [pending, retained) → pending；
  < pending → excluded。
- 硬规则优先于分数带：排除信号（`exclusion_terms`）命中 → excluded；
  无摘要 → pending（信息不足）。标签依据写入每条的 `label_basis`。

## 平局协议

`tie_break_order`（默认 S1→S2→S3→S4→S5→S6）：总分相同（容差
`tie_epsilon`，默认 1e-6）时按此序逐信号比较；再平 → 年份新→旧；再平
→ `record_id` 字典序。所有键仍相同 → 编入 `tie_group`（T1、T2…），
组内并列、如实标注；top-k 边界切到平局组时整组纳入并写 `top_k_note`。

## 敏感性检验

`sensitivity_perturb_pct`（默认 0.25）：对每个非零权重做单因子 ±25%
扰动（其余权重不动，整体归一化后重排），报告每个扰动下 top-k 新增/
移出与全体记录的最大名次位移。基线 top-k 条目在全部扰动下均留在
top-k → `stable`，否则 → `unstable` 并列出失守的扰动。敏感性比较采用
严格前 k（不做平局组扩展），与最终交付的 top-k 扩展规则相互独立。

## 证据纪律

每个信号的证据片段必须是该记录 title/abstract（S4 的 venue 启发为
venue 字段）的**原文子串**；脚本逐条自检，不过则该信号计 0 并告警。
S5/S6 的"证据"是字段存在性清单，不适用子串校验。任何情况下不用输入
夹具标注（provenance）作为打分依据。
