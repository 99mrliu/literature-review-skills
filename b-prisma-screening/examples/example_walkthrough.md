# 示意流程（合成示例，仅说明接口，非任何正式案例的结果）

语料：D1 期刊版全文、D2 会议版（与 D1 同研究）、D3 综述、D4 相关但对象为其他任务、D5 仅摘要。

1. `run_case.py init` → docs.jsonl（D1 fulltext；D5 abstract_only），dedup.py 检出 {D1, D2} 前缀重复组。
2. 模型写 criteria.md：IC1 报告 Y 任务上的性能对比（需全文）；IC2 对象为 Y；EC1 非原始研究；EC2 对象不符；EC3 重复发表。
3. 模型写 screening_log.json：题录/摘要轮 D1 include(IC1,IC2)、D2 duplicate_of(rep=D1)、D3 exclude(EC1)、D4 exclude(EC2)、D5 include(IC1 待全文确认)；全文轮 D1 include、D5 include(abstract_only_review, 摘要满足 IC1/IC2)。
4. `run_case.py audit` → pass（若 D4 的 exclude 漏写 criteria_ids 则 fail 并指明）。
5. 模型写 digests、themes.md、evidence_table.jsonl（含 D4 不纳入故无证据行）、review_draft.md。
6. `run_case.py finalize` → prisma_flow.json：identified 5 → after_dedup 4 → 筛序 4（排除 2）→ 全文复核 2（排除 0）→ 纳入 2；result.json status=completed。

以上文献均为演示虚构。
