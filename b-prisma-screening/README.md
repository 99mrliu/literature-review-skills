# prisma-repro-screening

文献综述生成的"筛选优先"协议：标准先行（IC/EC 编号条款）→ 显式去重 → 两轮筛选逐篇留痕 → 脚本推导 PRISMA 流程 → 在其上生成带定位引用的综述草稿。

## 快速开始（Harbor 运行时）

```bash
S=/skills/weekly-skill/scripts
python3 $S/run_case.py init --case /input/case.json --task /input/task.md --input-dir /input --work /app/work --out /app/output
# 模型: 写 criteria.md → screening_log.json
python3 $S/run_case.py audit --work /app/work --out /app/output
# 模型: digests → themes.md → evidence_table.jsonl → review_draft.md
python3 $S/run_case.py finalize --case /input/case.json --work /app/work --out /app/output
```

## 依赖

Python 3.8+，仅标准库。PDF 抽取优先 `pdftotext`，回退 pypdf，再回退纯文本。无网络依赖。

## 输出

`/app/output/result.json`（mirror output_contract）、`review_draft.md`、`audit_report.json`、`prisma_flow.md/json`。

## 自检

- audit 非 pass → 按 audit_report.json 修复 screening_log 后重跑。
- result.json `status` 非 completed → 读 uncertainties 定位是材料问题还是流程缺步。

详见 SKILL.md 与 rules/。
