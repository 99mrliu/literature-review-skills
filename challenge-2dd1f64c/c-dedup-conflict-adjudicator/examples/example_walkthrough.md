# 走查示例（示例/虚构，非任何案例答案）

> 本示例中的论文、作者、DOI、摘要全部为虚构，仅演示技能在三种典型情形
> 下的行为：① 确证重复簇（预印本 vs 正式版）自动合并；② 疑似对进复核
> 队列由模型裁决；③ 同 DOI 两导出年份矛盾升级人工。正式运行一律以真实
> 快照为准。

## 输入片段（虚构 case.json）

```json
{"case_id": "demo-000",
 "research_question": "认知训练对老年人工作记忆的效果如何？",
 "candidates": [
  {"id": "p1", "title": "Cognitive Training Improves Working Memory in Older Adults",
   "authors": ["Ana Silva", "Bo Li"], "year": 2021,
   "venue": "arXiv", "doi": "10.48550/arXiv.2107.12345",
   "abstract": "We report a randomized trial of adaptive cognitive training ..."},
  {"id": "p2", "title": "Cognitive training improves working memory in older adults.",
   "authors": ["Silva, Ana", "Bo Li"], "year": 2022,
   "venue": "Journal of Cognitive Aging", "doi": "10.1000/jca.2022.001",
   "abstract": "We report a randomized trial of adaptive cognitive training ..."},
  {"id": "p3", "title": "Cognitive Training and Everyday Functioning in Older Adults",
   "authors": ["Carla Mendes"], "year": 2019,
   "venue": "Gerontology Review", "abstract": "A narrative review of training ..."},
  {"id": "p4", "title": "Cognitive Training Effects on Working Memory in Older Adults: A Replication",
   "authors": ["Ana Silva"], "year": 2021, "venue": "Replication Studies",
   "abstract": "An independent replication with a preregistered design ..."},
  {"id": "p5", "title": "A Meta-Analysis of Memory Interventions",
   "authors": ["Dana Roth"], "year": 2020, "venue": "Meta Journal",
   "doi": "10.9999/meta.555", "abstract": "Pooled effects across 41 trials ..."},
  {"id": "p6", "title": "A Meta-Analysis of Memory Interventions",
   "authors": ["Dana Roth"], "year": 2019, "venue": "Meta Journal",
   "doi": "10.9999/meta.555", "abstract": "Pooled effects across 41 trials ...",
   "fixture": "synthetic duplicate export / conflicting opinions"}
 ]}
```

## 步骤 1：normalize

产出 6 条记录（R…P5、R…P6 按 id 派生 record_id）；p6 的 fixture 标注
原样存入 `provenance_note`，不作裁决依据；`/app/output/result.json`
写 `status="partial"` 骨架。

## 步骤 2：fingerprint

`pairs.jsonl` 关键行（节选）：

| 对 | title_jaccard | author_overlap | year_diff | doi_match | 判定档 |
| --- | --- | --- | --- | --- | --- |
| p1–p2 | 1.0000 | 1.0000 | 1 | false | `version_variant`（标题指纹相等、载体/年份不同，信号 `exact_title, venue_or_year_differs`） |
| p3–p4 | ≈0.78 | 0.0 | 2 | false | `independent`（作者重合度不足，R1 阈值带不生效） |
| p1–p4 | ≈0.82 | ≥0.5 | 0 | false | `suspected_duplicate`（阈值带内，**不自动合并**） |
| p5–p6 | 1.0000 | 1.0000 | 1 | true | `confirmed_duplicate`（`doi_match`） |

`clusters.json`：version_variant_clusters=[p1,p2]；confirmed_clusters=[p5,p6]；
suspected_pairs=[(p1,p4)]。

## 步骤 3：conflicts

`conflict_ledger.json`（节选）：

- CF01 / R3 / field_contradiction / field=year / p5(2020) vs p6(2019)：
  同 DOI 两导出年份矛盾，建议值为空、**升级人工**（R3：年份矛盾是导出
  错误信号，不猜）。
- CF02 / R5 / fixture_annotation_disagreement：p6 标注为
  “synthetic duplicate export”，指纹判定与 p5 同 DOI 确证重复——结论与
  标注一致，仍记录条目并注明“依据是指纹而非标注”。（若指纹**不**支持
  重复，同样生成该条目并升级人工。）

## 步骤 4：模型写 adjudications.jsonl

```json
{"ids":["Rp1","Rp4"],"decision":"reject_merge","reason":"p4 为 preregistered 独立 replication，摘要明言 independent replication；同题不同工作"}
{"ids":["Rp5","Rp6"],"decision":"escalate","reason":"同 DOI 年份矛盾（2020 vs 2019），快照无法裁决，升级人工"}
```

## 步骤 5：merge + queue

- 簇 [p1,p2]：按 R2，p2 是正式同行评审版（Journal of Cognitive Aging），
  p1 是预印本 → canonical=p2，`merge_kind="version_variant"`，p1 记入
  `merged_from` 并保留于 `merged_into`。
- 簇 [p5,p6]：R2 并列（venue、年份矛盾）→ 元数据完整度与 record_id 序
  决定 canonical；年份字段的真实值留待人工。
- 疑似对 [p1,p4] 被模型 reject_merge → `merge_map.rejected_pairs`，
  两条保持独立。
- `review_queue.json` 收录 CF01 升级项（冲突）与 p5/p6 的年份裁决请求。

## 步骤 6–7：筛选 + assemble

模型对 5 条 canonical 逐条写 `screening.jsonl`（retained/pending/
excluded + 原文子串引用 + 理由 + 置信度）。`assemble.py` 校验：
V1 5/5 覆盖；V2 引用均为摘要子串；V3 6 条原始记录恰好出现一次
（p1 出现在 p2 的 merged_from，p6 出现在 p5/p6 簇成员中）；V4 合同字段
齐。输出 `result.json`（status=`complete_with_open_review`，因复核队列
非空）与 `adjudication_report.md`（簇表、合并理由、冲突裁决表、
人工复核队列、筛选裁决表）。

**本例要点回顾**：确证簇自动合并但留痕；疑似对只有模型 confirm 才合并；
同 DOI 年份矛盾绝不猜测、一律升级；夹具标注只进 provenance，不改裁决。
