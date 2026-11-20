# 完整走查示例（虚构数据，仅作示意）

> 本示例的研究问题、文献题录与摘要均为**虚构**，仅用于演示
> prepare → score → sensitivity → assemble 全链路的输入输出形态。
> 正式运行必须以真实 case.json 与 task.md 为准。所有片段为脚本真实输出
> 的摘录。

## 1. 输入（虚构）

`case.json`（3 条候选；R003 为大鼠动物实验 + 预印本 venue）：

```json
{"case_id": "demo-fictional-001",
 "research_question": "In adults with major depression, does transcranial magnetic stimulation (TMS) improve outcomes?",
 "records": [
  {"title": "Repetitive TMS for major depression in adults: a randomized sham-controlled trial",
   "abstract": "We randomized 220 adults with major depression to repetitive transcranial magnetic stimulation or sham. ...",
   "authors": ["J. Doe", "A. Smith"], "year": 2023, "venue": "Brain Stimulation", "doi": "10.9999/demo1"},
  {"title": "TMS versus antidepressants in elderly depression: a retrospective cohort",
   "abstract": "A retrospective cohort of elderly adults with depression treated with transcranial magnetic stimulation or antidepressants, with 12-month follow-up.",
   "authors": ["B. Roe"], "year": 2019, "venue": "J Affect Disord", "doi": "10.9999/demo2"},
  {"title": "TMS-like stimulation in a rat model of depression",
   "abstract": "We applied TMS-like stimulation to rats with induced depressive behavior. Animal study only.",
   "authors": ["C. Moe"], "year": 2021, "venue": "medRxiv"}]}
```

## 2. prepare

```bash
python3 "$SKILL_DIR/scripts/prepare.py" --case case.json --work /app/work --out /app/output
# → records=3, metadata_gaps=0, records.jsonl / case_meta.json / rubric.json / result.json(partial)
```

归一化产物 `/app/work/records.jsonl`（每行一条，record_id 为 R001–R003，
缺失字段保持 null 并计入 metadata_gaps，本例无缺失）。

## 3. 模型一次性翻译：criteria_terms.json（示意）

```json
{"research_question": "In adults with major depression, does TMS improve outcomes?",
 "topic_terms": ["transcranial magnetic stimulation", "TMS", "depression"],
 "population_terms": ["adults", "major depression"],
 "method_terms": ["randomized", "sham", "cohort"],
 "evidence_level_preference": ["meta_analysis", "rct", "systematic_review",
   "cohort", "case_control", "cross_sectional", "review", "preprint", "unknown"],
 "recency_years": 10,
 "exclusion_terms": ["rat", "animal"]}
```

## 4. score（脚本）

```bash
python3 "$SKILL_DIR/scripts/rank_engine.py" score \
    --work /app/work --terms /app/work/criteria_terms.json \
    --rubric /app/work/rubric.json --out /app/work/scored.jsonl
# → counts: {"retained": 2, "pending": 0, "excluded": 1}, ref_year=2023
```

scored.jsonl 首行（R001，节选）：注意每个 evidence.snippet 都是标题/摘要
原文子串，脚本已自检。

```json
{"record_id": "R001",
 "signals": {
  "S1_topic": {"score": 0.6667,
   "hits": ["TMS", "depression", "transcranial magnetic stimulation"],
   "evidence": [{"term": "TMS", "snippet": "TMS", "field": "title"},
                {"term": "depression", "snippet": "depression", "field": "title"},
                {"term": "transcranial magnetic stimulation",
                 "snippet": "transcranial magnetic stimulation", "field": "abstract"},
                {"term": "depression", "snippet": "depression", "field": "abstract"}],
   "note": "标题命中 2/3 词，摘要命中 2/3 词（标题权重 0.70）"},
  "S4_evidence_level": {"score": 0.8889, "level": "rct",
   "evidence": [{"snippet": "sham-controlled", "field": "title", "term": "rct"}],
   "note": "判定层级 rct（偏好序位 2/9）"}},
 "signal_scores": {"S1_topic": 0.6667, "S2_population": 1.0, "S3_method": 0.6667,
                   "S4_evidence_level": 0.8889, "S5_recency": 1.0, "S6_metadata": 1.0},
 "total_score": 0.8333, "label": "retained",
 "label_basis": "total_score 0.833 >= retained 0.65"}
```

模型随后抽查（第 5 步）：例如确认 `sham-controlled` 确为 R001 标题子串、
R003 的 `『rat』『Animal』` 排除命中确在原文中。

## 5. sensitivity（脚本，k=2）

```bash
python3 "$SKILL_DIR/scripts/rank_engine.py" sensitivity --work /app/work --k 2
# → 基线 top-2 共 2 条；12 个单因子 ±25% 扰动下，2 条全程稳定在 top-2，0 条不稳定。
```

sensitivity.json 中单个扰动记录（节选）：

```json
{"signal": "S2_population", "direction": "+25%", "weight_before": 0.2,
 "weight_after_raw": 0.25, "topk": ["R001", "R002"],
 "added": [], "removed": [], "max_rank_displacement": 0}
```

稳定性判定：`{"R001": {"verdict": "stable", "fails_under": []},
"R002": {"verdict": "stable", "fails_under": []}}`。
（若某条在某扰动下跌出 top-k，则记 `unstable` 并列出失守扰动，例如
`"fails_under": ["S4_evidence_level -25%"]`。）

## 6. assemble（脚本，k=2）

```bash
python3 "$SKILL_DIR/scripts/rank_engine.py" assemble \
    --work /app/work --out /app/output --k 2
# → status=complete, top_k=["R001", "R002"]
```

ranking_report.md 评分卡总表（节选）：

```
| rank | record | 总分 | S1主题 | S2人群 | S3方法 | S4证据层级 | S5时间 | S6元数据 | 标签 | 置信 | 平局组 | 稳定性 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | R001 | 0.833 | 0.67 | 1.00 | 0.67 | 0.89 | 1.00 | 1.00 | retained | high | — | stable |
| 2 | R002 | 0.650 | 0.67 | 0.50 | 0.33 | 0.67 | 1.00 | 1.00 | retained | high | — | stable |
| 3 | R003 | 0.393 | 0.57 | 0.00 | 0.00 | 0.22 | 1.00 | 0.90 | excluded | high | — | not_assessed |
```

result.json 中 R002 的逐条理由（脚本自动生成，可复核）：

> 加权总分 0.650；S1主题=0.67，证据 『TMS』、『depression』、
> 『transcranial magnetic stimulation』；S2人群=0.50，证据 『adults』；
> S3方法=0.33，证据 『cohort』；S4证据层级=0.67（层级 cohort），证据
> 『cohort』；S5时间=1.00；S6元数据=1.00（字段齐备）；标签 retained
> （依据：total_score 0.650 >= retained 0.65）

注意 R002 总分恰好落在 retained 阈值 0.65 上（`>=` 判定为 retained），
阈值语义见 `references/rubric.md`。R003 因排除信号 `rat`/`animal` 命中
被硬排除，其理由中同时列出排除证据与 preprint venue 证据
（`『medRxiv』`），排除依据优先于分数带。

## 7. 本例未触发、但脚本已覆盖的情形

- 平局组（tie_group）与 top-k 整组扩展：见自测（5 条记录中含一对完全
  重复导出，二者同分组 T1，k=2 时整组 3 条纳入并写 top_k_note）。
- 无摘要 → pending + confidence=low；缺年份 → S5 权重再分配。
- 空候选集 → `status="empty_result"` 合法交付。
- criteria_terms.json 的 `topic_terms` 为空 → score 非零退出，拒绝
  "空词表假装打分"。
