# 筛选留痕模板

## criteria.md

```markdown
# 筛选标准（先于阅读结论写定）

研究问题：<原句>

## 方面分解
- 对象：……
- 方法/干预：……
- 结局/指标：……

## 纳入标准
- IC1: ……（题录级可判定 / 需全文）
- IC2: ……

## 排除标准
- EC1: 综述、社论或评论等非原始研究
- EC2: ……
```

## screening_log.json

```json
{
  "phases": [
    {"phase": "title_abstract", "records": [
      {"doc_id": "D1", "decision": "include", "criteria_ids": ["IC1", "IC3"], "reason": "摘要明确报告 Y 任务性能对比"},
      {"doc_id": "D2", "decision": "exclude", "criteria_ids": ["EC2"], "reason": "研究对象为 Z 而非 Y"},
      {"doc_id": "D4", "decision": "duplicate_of", "criteria_ids": [], "reason": "与 D1 同标题同作者", "representative": "D1"}
    ]},
    {"phase": "fulltext", "records": [
      {"doc_id": "D1", "decision": "include", "criteria_ids": ["IC1", "IC3"], "reason": "全文确认实验设置满足 IC3"}
    ]}
  ]
}
```

填写后运行 `python3 <scripts>/run_case.py audit --work /app/work --out /app/output`，按 audit_report.json 修复。
