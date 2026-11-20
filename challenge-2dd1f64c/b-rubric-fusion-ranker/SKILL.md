---
name: rubric-fusion-ranker
description: >-
  文献筛选与智能排序——评分卡融合排序与稳健性检验。当任务给出明确研究问题与一份
  有限候选文献快照，要求给出"把真正相关文献排在前面"的可解释排序、逐条理由
  与三态标签时触发。差异化能力：模型只做一次性翻译（研究问题→criteria_terms.json
  词表），六个信号（主题/人群/方法/证据层级/时间窗/元数据质量）的打分、加权
  融合、平局协议、top-k 边界扩展、单因子 ±25% 权重敏感性检验全部由确定性
  脚本完成，模型零心算；每条信号的打分必须绑定 title/abstract 原文子串证据，
  脚本自检证据确为原文（不过则信号计 0 并告警）；权重带内不稳定条目如实
  标注 stable/unstable；空候选集、缺摘要/年份、输入夹具标注全部显式入账。
---

# rubric-fusion-ranker：评分卡融合排序 + 逐条理由 + 敏感性稳健性检验

## 适用场景与边界

- 适用：给定研究问题 + 候选文献快照（题录/摘要级元数据），输出一份
  **可解释、可复算、可复核**的相关性排序：每条候选带 6 信号分数分解、
  原文证据片段、自动生成的逐条理由、三态标签（retained/pending/excluded）
  与权重敏感性结论。快照是有限证据集，一切判断只依据快照内证据。
- 边界（**不做**）：不联网检索、不声称全局召回、不阅读快照外全文、
  不臆造缺失的摘要/年份/作者、不做学习式打分（权重与阈值是显式的
  评分卡，见 `references/rubric.md`）、不删除任何候选记录（平局与疑似
  重复只标注，不合并）。
- 与筛选台账型方案的分工：本技能的核心交付是**排序的可解释性与稳健性**
  （分数分解 + 证据 + 敏感性报告），标签是排序分数带的副产品；若任务
  要求的是纳入/排除的协议化审计，请改用筛选台账技能。
- 核心失败模式防御：基础 Agent 的典型错误是"标题有关键词即排前"的
  词面排序、理由不可复核、同分随手排、k 值截断平局组、缺元数据随手
  补造。本技能把全部算术与协议交给脚本，模型的判断空间只剩"把研究
  问题翻译成词表"与"抽查证据片段"。

## 运行环境

- 两个 Python 3 **标准库**脚本，位于 `scripts/`：`prepare.py`、
  `rank_engine.py`（子命令 score / sensitivity / assemble），均有
  `--help`，致命错误以非零退出。无第三方依赖，无需网络。
- 默认安装路径 `/skills/weekly-skill`；若不在，先定位：

  ```bash
  SKILL_DIR=/skills/weekly-skill
  [ -f "$SKILL_DIR/scripts/rank_engine.py" ] || \
    SKILL_DIR=$(dirname "$(dirname "$(find / -maxdepth 5 -path '*/scripts/rank_engine.py' 2>/dev/null | head -1)")")
  python3 "$SKILL_DIR/scripts/rank_engine.py" --help
  ```

- 预算纪律：模型请求有限。`prepare.py` 一次跑完归一化与脚手架；模型
  只写一次 `criteria_terms.json`；打分、敏感性、组装全部脚本完成；
  模型最后抽查证据片段并过一遍自查清单。除词表外不在模型侧做任何
  数值计算。

## 工作流程（八步）

### 1. 读材料，固证

- 读 `/input/case.json` 与 `task.md`，提取 `case_id`、研究问题（候选键：
  `research_question` / `question` / `query` / `task` / `objective` 等）、
  输出合同（`output_contract` 字段清单）。
- **读真实文件**，不臆测来源内容。材料清单最终写入 `result.json` 的
  `sources`。

### 2. 归一化候选集并立即脚手架（先保底）

```bash
mkdir -p /app/work /app/output
python3 "$SKILL_DIR/scripts/prepare.py" \
    --case /input/case.json --task task.md --work /app/work --out /app/output
```

- 输出：`/app/work/records.jsonl`（稳定 `record_id` R001…、`source_id`、
  title/abstract/authors/year/venue/doi/url、`provenance`、raw_keys）、
  `/app/work/case_meta.json`（case_id、研究问题、合同字段、
  metadata_gaps）、`/app/work/rubric.json`（默认评分卡，供检查，一般不
  需要改）、`/app/output/result.json` 骨架（`status="partial"`）。
- 缺摘要/年份/作者不补造，逐条进 `metadata_gaps`；输入夹具标注
  （如"合成重复导出""冲突意见"）原样保留在 `provenance`，**只作来源
  记录，不作为排序依据**。

### 3. 模型一次性翻译：写 criteria_terms.json

依据研究问题，在 `/app/work/criteria_terms.json` 写出（仅此一次模型
判断，之后不再改分）：

```json
{
  "research_question": "（照抄或压缩原问题）",
  "topic_terms": ["主题词1", "主题词2", "..."],
  "population_terms": ["对象/人群词", "..."],
  "method_terms": ["方法/设计词", "..."],
  "evidence_level_preference": ["meta_analysis", "rct", "systematic_review",
     "cohort", "case_control", "cross_sectional", "review", "preprint", "unknown"],
  "recency_years": 10,
  "exclusion_terms": ["明确排除信号词", "..."]
}
```

纪律：

- `topic_terms` 必须非空，否则 score 拒绝运行（防止空词表假装打分）。
- 词应取快照文献里可能出现的**原词/原短语**（英文快照用英文词）；只
  覆盖快照可见证据，不引入需要全文才能判断的标准。
- `population_terms` / `method_terms` 留空 = 该信号不适用，权重按规则
  自动再分配（不是错误）；`exclusion_terms` 只放**命中即可硬排除**的
  强信号（如物种不符），慎用。
- `evidence_level_preference` 可重排以表达研究问题对证据层级的偏好；
  未知条目被脚本丢弃并告警。

### 4. 脚本打分

```bash
python3 "$SKILL_DIR/scripts/rank_engine.py" score \
    --work /app/work --terms /app/work/criteria_terms.json \
    --rubric /app/work/rubric.json --out /app/work/scored.jsonl
```

- 每条记录输出 6 信号分值、命中词、**原文子串证据**、加权总分（不可用
  信号的权重按比例再分配）、建议标签与依据。
- 证据自检：每个证据片段必须是该记录 title/abstract（或 venue）的原文
  子串；自检不过则该信号计 0 并告警，**不静默通过**。
- 打印的三态计数与告警必须读一遍；有告警先修复（多为词表问题）。

### 5. 模型抽查证据片段（核对，不重算）

- 从 scored.jsonl 抽 2–3 条（至少含一条高分、一条低分），把 evidence
  里的 snippet 与 records.jsonl 的原文比对：确为子串、词表没有明显
  误配（如把"review"当方法词）。发现问题只改 criteria_terms.json 后
  重跑 score，**不手改 scored.jsonl**。

### 6. 敏感性稳健性检验

```bash
python3 "$SKILL_DIR/scripts/rank_engine.py" sensitivity --work /app/work --k 5
```

- 对每个权重做单因子 ±25% 扰动（归一化后重排），输出
  `sensitivity.json` + `sensitivity_report.md`：每个扰动下 top-k 成员
  变化、最大名次位移、基线 top-k 逐条 stable/unstable 判定。
- k 的取值：任务指定则用任务值；未指定用 5；k ≥ 候选数时 top-k 即全集，
  敏感性结论退化为位移分析，脚本会如实标注。

### 7. 组装交付物

```bash
python3 "$SKILL_DIR/scripts/rank_engine.py" assemble \
    --work /app/work --out /app/output --k 5
```

产出（`/app/output/`）：

- `result.json`：合同字段 + `counts`、`ranked_results`（逐条含
  分数分解/证据/自动理由/label/confidence/tie_group/stability/
  provenance）、`top_k`（含平局组整组纳入说明）、`rubric_applied`、
  `sensitivity_summary`、`metadata_gaps`、`provenance_notes`、
  `uncertainty`、`sources`、`change_log`、`status`。
- `ranking_report.md`：权重表、阈值与平局协议、评分卡总表、逐条理由
  （可复核）、敏感性摘要、元数据缺口——人工审核者凭此即可复核定案。
- `scored.jsonl`、`criteria_terms.json`、`rubric.json`、`sensitivity.*`
  一并复制到输出目录，供独立重跑验证。

### 8. 异常与降级（显式入账，不静默）

- 空候选集：合法。score 输出空文件，assemble 交付
  `status="empty_result"`、counts 全 0 与原因说明。
- criteria_terms.json 缺失/坏 JSON/`topic_terms` 为空：score 非零退出
  并说明修什么；**不猜词表继续跑**。
- 词表条目类型错误、recency_years 非法、偏好层级拼错：丢弃该条目并
  告警，照常运行（诚实降级）。
- 缺摘要 → 该条 `pending`（信息不足），confidence=low；缺年份 → S5
  不可用、权重再分配；全部缺年份 → S5 全体不可用并告警。
- 缺 sensitivity.json 时 assemble 照常交付但 `status="partial"`，
  稳定性标 `not_assessed`。

## 排序与平局协议（确定性，写死在脚本里）

总次序 = 加权总分降序 → 按 `tie_break_order`（默认 S1→S2→S3→S4→S5→S6）
逐信号降序 → 年份新→旧（缺失排后）→ `record_id` 字典序。全部键仍相同
的记录进入同一 `tie_group`（T1、T2…）并列出 `tie_members`，不强行分出
先后；top-k 边界落在平局组上时**整组纳入**并在 `top_k_note` 注明。
换一批候选重跑，同一记录的相对位置只由上述键决定，保证可复现。

## 标签映射（阈值来自 rubric.json，可解释）

1. 排除信号命中 → `excluded`（硬规则，优先级最高）；
2. 无摘要 → `pending`（信息不足，待补材料才能改判）；
3. 总分 ≥ retained 阈值（默认 0.65）→ `retained`；
4. 总分 ∈ [pending 阈值, retained 阈值)（默认 [0.40, 0.65)）→ `pending`；
5. 低于 pending 阈值 → `excluded`（分数带排除，理由写明阈值）。

confidence（脚本确定性派生）：无摘要 → low；证据层级 unknown 或有信号
不可用 → medium；其余 → high。

## 输出合同缺省

若 `case.json` 未给出 `output_contract`，`result.json` 至少包含：
`case_id`、`status`、`research_question`、`counts`（total/retained/
pending/excluded）、`k`、`top_k`、`ranked_results`、`rubric_applied`、
`tie_groups`、`sensitivity_summary`、`metadata_gaps`、
`provenance_notes`、`uncertainty`、`sources`、`change_log`。合同给出
字段清单时以合同为准并保留上述审计字段。

## 自查清单（交付前逐项确认）

- [ ] scored.jsonl 行数 = records.jsonl 行数；counts 三态之和 = 候选总数；
- [ ] 抽查的证据片段确为原文子串，scored.jsonl 无未读告警；
- [ ] 排序前列确实是真正相关文献（高分条目的理由读得通）；
- [ ] tie_group 已标注；top-k 边界切到平局组时已整组纳入并注明；
- [ ] 无摘要/年份/作者的记录在 metadata_gaps 中，未补造；
- [ ] provenance（夹具标注）只作来源记录，未影响排序；
- [ ] 敏感性报告已生成，unstable 条目在 result.json 与报告中一致标注；
- [ ] `status` 与实际完成度一致（empty_result / partial 均有说明）；
- [ ] ranking_report.md 可供未参与本任务的人逐条复核。

## 最小调用示例（示意，非案例答案）

```bash
SKILL_DIR=/skills/weekly-skill
python3 "$SKILL_DIR/scripts/prepare.py" \
    --case /input/case.json --task task.md --work /app/work --out /app/output
# 模型写词表（内容为示意）：
cat > /app/work/criteria_terms.json <<'EOF'
{"topic_terms": ["transcranial ultrasound", "neuromodulation"],
 "population_terms": ["adults"], "method_terms": ["randomized", "sham"],
 "recency_years": 10, "exclusion_terms": ["mice", "rat model"]}
EOF
python3 "$SKILL_DIR/scripts/rank_engine.py" score \
    --work /app/work --terms /app/work/criteria_terms.json \
    --rubric /app/work/rubric.json --out /app/work/scored.jsonl
python3 "$SKILL_DIR/scripts/rank_engine.py" sensitivity --work /app/work --k 5
python3 "$SKILL_DIR/scripts/rank_engine.py" assemble \
    --work /app/work --out /app/output --k 5
```

示例中的词表为虚构示意，正式运行必须以真实研究问题与真实快照为准。
完整走查（含输出片段）见 `examples/example_walkthrough.md`。
