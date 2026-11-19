# quote-gated-evidence-ledger

文献综述生成的"逐字引用门控"协议：筛选 → 主题归纳 → 证据组织 → 草稿，每一步都带可回查定位，交付前由脚本校验每条摘录确实出现在所声称的文档位置。

## 快速开始（Harbor 运行时）

```bash
S=/skills/weekly-skill/scripts
python3 $S/run_case.py init --case /input/case.json --task /input/task.md --input-dir /input --work /app/work --out /app/output
# 模型阶段: 按 SKILL.md 第 5 节写 screening.md / digests / themes.md / evidence_ledger.jsonl / review_draft.md
python3 $S/run_case.py verify --work /app/work --out /app/output
python3 $S/run_case.py finalize --case /input/case.json --work /app/work --out /app/output
```

## 依赖

Python 3.8+，仅标准库。PDF 文本抽取优先使用环境的 `pdftotext`，缺失时回退 pypdf，再回退纯文本。无外部网络依赖。

## 输出

`/app/output/result.json`（mirror case 的 output_contract + case_id + status + sources + uncertainties + change_log）、`review_draft.md`、`gate_report.json`。证据表只收录通过核验的行。

## 失败模式自检

- `gate_report.json` 中 `status != pass` → 回到 evidence_ledger 修正 locator/quote 后重跑 verify。
- result.json `status = partial/blocked` 时，先读 `uncertainties` 与 `change_log`，确认是材料问题还是流程未完成。

详细协议见 SKILL.md。
