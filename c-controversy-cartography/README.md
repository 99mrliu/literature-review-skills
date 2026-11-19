# controversy-gap-cartography

文献综述生成的"冲突与空白制图"协议：主题由语料聚类长出 → 论断带方向与定位 → 矛盾对显式裁决 → 空白从证据分布推导 → 草稿按"主张—证据—反证—缺口"逐主题成文，附共识梯度。

## 快速开始（Harbor 运行时）

```bash
S=/skills/weekly-skill/scripts
python3 $S/run_case.py init --case /input/case.json --task /input/task.md --input-dir /input --work /app/work --out /app/output
# 模型: claims.jsonl → themes.md + themes_map.json → controversy_matrix.md → gaps.md → review_draft.md
python3 $S/run_case.py check --work /app/work --out /app/output
python3 $S/run_case.py finalize --case /input/case.json --work /app/work --out /app/output
```

## 依赖

Python 3.8+，仅标准库。PDF 抽取优先 `pdftotext`，回退 pypdf，再回退纯文本。无网络依赖。

## 输出

`/app/output/result.json`（mirror output_contract）、`review_draft.md`、`structure_report.json`；中间产物（主题图、矛盾矩阵、空白图）随 result.json 的 screening_log 字段一并交付。

## 自检

- check 非 pass → 按 structure_report.json 修复后重跑。
- result.json `status` 非 completed → 读 uncertainties 定位。

详见 SKILL.md 与 rules/。
