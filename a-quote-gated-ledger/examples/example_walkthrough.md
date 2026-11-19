# 示意流程（合成示例，仅说明接口，非任何正式案例的结果）

假设 `/input/case.json` 含 `{"case_id":"demo","research_question":"X 方法是否提升 Y 任务性能","documents":[{"path":"/input/a.pdf","title":"A"},{"path":"/input/b.pdf","title":"B"},{"path":"/input/c.pdf","title":"C"}]}`。

1. `run_case.py init` → `docs.jsonl` 三行（D1 fulltext, D2 fulltext, D3 abstract_only），`pages/D1.jsonl` 等锚点文件，partial result.json 已写入。
2. 模型写 `screening.md`：IC1 直接报告 Y 任务上的性能；EC1 仅理论分析无实验……逐篇决定：D1 include(IC1)，D2 include(IC1)，D3 include-with-caution(abstract_only)。
3. 模型写三份 `digests/D*.md`，再写 `themes.md`：T1 基准内性能（D1, D2）、T2 跨域泛化（仅 D1 报告）。
4. 模型写 `evidence_ledger.jsonl`：E1(D1 p3.¶2, "…improved F1 by 4.1 points…", established)、E2(D2 p5.¶1, "…gains did not transfer…", contested)、E3(D3 p1.¶1, 摘要句, suggestive)……
5. 模型写 `review_draft.md`：T1 节"两项研究报告基准内提升 [E1;E3]；然而跨域迁移证据相反 [E2]……[证据缺口: 无第三方复现]"。
6. `run_case.py verify` → gate 校验 E1–E3 摘录逐字命中；若 E2 的 locator 写错页，该句被降级为 `[未核验:E2]`，gate_report.json 记录原因。
7. `run_case.py finalize` → result.json（status=completed，evidence_matrix 只含 verified 行）。

以上文献与数字均为演示虚构。
