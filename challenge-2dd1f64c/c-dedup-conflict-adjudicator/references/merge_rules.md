# 合并与裁决规则 R1..R6

本文件是 `scripts/dedup_engine.py` 的规范文本。脚本是规则的机械执行者；
模型的 `adjudications.jsonl` 可以确认或推翻脚本的判定档与建议，但必须写明
理由（R4）。规则编号在 `conflict_ledger.json` 与 `merge_map.json` 中引用。

## R1 指纹与判定档

### 三类指纹

1. **标题指纹**：小写；去标点；去停用词（冠词 the/a/an 及 and、of、on、
   in、for、to、with、by、at、from、is/are/was/were、using/via 等）；
   含中日韩字符时退化为去标点后的字符 bigram 集合。相似度 = token 集合
   的 Jaccard 系数（`title_jaccard`）。
2. **DOI 指纹**：小写，剥去 `https://doi.org/`、`doi:` 前缀；归一化后
   字符串相等即 `doi_match=true`。
3. **（首作者姓 + 年份）指纹**：首作者规范化姓（去标点小写，兼容
   “姓, 名”与“名 姓”两种写法）拼接年份。

### 成对判定档（按顺序首条命中生效）

| 档位 | 条件 | 含义 |
| --- | --- | --- |
| `confirmed_duplicate` | DOI 指纹相等；**或** 标题指纹完全相等且年份一致；**或** `title_jaccard ≥ 0.95` 且 `author_overlap ≥ 0.5` | 确证重复，可自动合并 |
| `version_variant` | 标题指纹完全相等但年份/载体不同；**或** `title_jaccard ≥ 0.85` 且 `author_overlap ≥ 0.5` 且年份或载体不同 | 同一工作的版本变体（如预印本↔正式版），按 R2 合并保留版本信息 |
| `suspected_duplicate` | `title_jaccard ∈ [0.60, 0.95)` 且 `author_overlap ≥ 0.5` 且年份差 ≤ 2；**或** （首作者姓+年份）指纹相等且 `title_jaccard ≥ 0.5` | 疑似，**不自动合并**，进复核队列，由模型 confirm/reject/escalate |
| `independent` | 以上均不满足 | 独立记录 |

`author_overlap` = 规范化姓集合的包含度（交集 / min(两侧大小)）。
所有候选两两比较，`pairs.jsonl` 对每一对输出完整相似度分解
（title_jaccard、author_overlap、year_diff、doi_match、
title_fp_equal、first_author_year_match）与判定档，供人工复核。

## R2 canonical 选择顺序

簇内选择 canonical 记录，依次比较，并列才进入下一级：

1. 载体优先级：**正式同行评审版 > 预印本**（venue 非空且非预印本模式
   arXiv/bioRxiv/medRxiv/chemRxiv/preprint 者胜）；
2. **元数据完整度高者**（title/abstract/year/venue/doi/url 各占 1 分，
   作者按 3 人封顶计分）；
3. **年份新者**优先；
4. 仍并列 → `record_id` 字典序较小者。

模型的 `canonical_hint` 可以指定 canonical，但必须在 `reason` 中给出
优于 R2 顺序的理由，否则以 R2 为准。

## R3 字段冲突优先级与建议裁决

扫描范围：**确证重复组**（同一工作、同一导出族）。`version_variant`
簇的 venue/year 差异是其定义性特征（预印本 2021 vs 正式版 2022 属正常
版本演进），不算矛盾，不入冲突台账。

同一重复组内出现字段矛盾时，来源优先级为：
**带 DOI 的导出 > 正式同行评审记录 > 预印本 > 纯检索导出**。

- **venue 矛盾**：优先级可区分 → 建议取高优先级方的值（不升级）；
  优先级相同 → 升级人工。
- **year 矛盾**：无论优先级是否可区分，一律记录冲突。优先级可区分时
  给出建议值，**但标记升级**——同一工作两个导出年份不同是导出错误信号，
  快照内证据不足以断言正确年份。
- **DOI 矛盾**（重复组内两个不同 DOI）：机器无法判定哪个 DOI 正确，
  无建议值，升级人工。
- **authors 矛盾**（重复组内作者集合不相交）：与重复判定本身冲突，
  升级人工。
- 任何被升级或建议的裁决，模型的 `adjudications.jsonl` 可以用
  `"decision": "confirm_merge"` 附带裁决值覆盖脚本建议，但必须在
  `reason` 中引用快照内证据；无证据则维持升级。

## R4 升级条件与裁决留痕

- 触发升级：疑似对模型无法确认（不裁决或 escalate）；字段矛盾按 R3
  需升级；夹具标注与指纹结论不一致（R5）；记录无法解析或缺标题。
- 升级即**终态入账**：进入 `review_queue.json`，`status` 记
  `escalated` 或 `open`，写明所需人工动作。**绝不猜测填充裁决值**。
- 模型的每次确认/推翻/升级都写入 `adjudications.jsonl`，含 `ids`、
  `decision`（confirm_merge / reject_merge / escalate）、`reason`；
  可附 `canonical_hint`。脚本据此覆盖自身建议，覆盖记录保留在
  `merge_map.model_overrides` 计数中。

## R5 夹具标注纪律

输入中的“合成重复导出/冲突意见”等标注（`provenance_note`）**只作
provenance 提示保留**，不作为任何裁决依据。技能用指纹独立验证；若标注
声称重复而指纹未将相关记录归入任何重复簇，或反之，生成
`fixture_annotation_disagreement` 冲突条目（升级人工），说明“标注为夹具
提示，不作为裁决依据”。结论与标注一致时也要在报告中注明依据是指纹而
非标注。

## R6 合并完整性（绝不静默删除）

- 簇内每个成员都记录在 canonical 条的 `merged_from` 中（含各自 title/
  year/venue/doi/source_keys/provenance_note）。
- 被合并条目不消失：在 `merge_map.merged_into` 中保留
  `成员 record_id → canonical record_id` 映射。
- merge 与 assemble 双重校验：每条原始记录在结果中**恰好出现一次**
  （canonical 或某 `merged_from` 成员），校验不过非零退出、不交付。
- 合并只发生在 confirmed 簇与模型 confirm_merge 的疑似对；版本变体合并
  在 `merge_kind` 中记 `version_variant`，版本信息（旧载体、旧年份）仍在
  `merged_from` 中可查。
