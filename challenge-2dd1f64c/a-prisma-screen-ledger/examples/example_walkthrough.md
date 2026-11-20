# 示例：三段走查（虚构数据，仅演示接口与流程）

> 本文件为**接口示意**，题录与引用均为虚构，不对应任何正式案例结果。

## 1. 输入（虚构 case.json 片段）

```json
{
  "case_id": "demo-01",
  "research_question": "抗阻训练对绝经后女性骨密度影响的随机对照试验",
  "candidates": [
    {"id": "a1", "title": "Resistance training and bone mineral density in postmenopausal women: a randomized trial",
     "abstract": "In a randomized trial of 214 postmenopausal women, 12 months of supervised resistance training increased lumbar spine BMD by 1.8% vs controls.", "year": 2019, "venue": "J Bone Miner Res", "doi": "10.0000/demo1"},
    {"id": "a2", "title": "Exercise effects on bone in murine models",
     "abstract": "Twelve-week treadmill exercise in ovariectomized mice altered trabecular bone.", "year": 2021, "venue": "Bone Rep"},
    {"id": "a3", "title": "Physical activity and skeletal health",
     "abstract": null, "year": null, "venue": null}
  ]
}
```

## 2. 标准（criteria.json，示意）

```json
{
  "inclusion": {"I1": "主题为抗阻/力量训练干预", "I2": "对象为绝经后女性", "I3": "设计为随机对照试验", "I4": "结局含骨密度"},
  "exclusion": {"E1": "研究对象为非人类动物", "E2": "主题与核心干预不符"}
}
```

## 3. 裁决（decisions.jsonl，示意）

```json
{"record_id": "Ra1", "label": "retained", "criteria": ["I1", "I2", "I3", "I4"], "criteria_missed": [], "quote": "randomized trial of 214 postmenopausal women", "evidence_field": "abstract", "confidence": "high", "reason": "人群/设计/结局全部直接命中"}
{"record_id": "Ra2", "label": "excluded", "criteria": ["E1"], "criteria_missed": ["I2"], "quote": "ovariectomized mice", "evidence_field": "abstract", "confidence": "high", "reason": "E1：研究对象为小鼠"}
{"record_id": "Ra3", "label": "pending", "criteria": [], "criteria_missed": ["I1", "I2", "I3", "I4"], "quote": "Physical activity and skeletal health", "evidence_field": "title", "confidence": "low", "reason": "摘要与年份缺失，无法判断对象与设计；需获取摘要全文改判"}
```

## 4. 运行

```bash
python3 scripts/prepare.py --case demo.json --task task.md --work /app/work --out /app/output
# （模型写 criteria.json 与 decisions.jsonl）
python3 scripts/ledger.py check --work /app/work --out /app/output
# → CHECK RESULT: PASS
python3 scripts/ledger.py assemble --work /app/work --out /app/output
# → result.json / screening_report.md / criteria.json / decisions.jsonl
```

注意：Ra3 的 quote 来自标题（abstract 为 null），evidence_field 如实标注；
Ra3 同时进入 result.json 的 metadata_gaps（缺 abstract 与 year）。
