---
name: dedup-conflict-adjudicator
description: >-
  文献筛选与智能排序——去重指纹、版本合并与冲突裁决的可审计规则系统。当任务给出
  一份有限候选文献快照（约 9 篇、可能来自多次导出），其中混有重复条目、
  预印本与正式版同题并存、同一成果不同导出字段互相矛盾、或输入夹具声明
  “合成重复导出/冲突意见”时触发。差异化能力：规范化标题/DOI/（首作者+年份）
  三类指纹，对全部候选做成对相似度分解并输出判定档（确证重复簇 / 疑似重复 /
  版本变体 / 独立）；簇内按 R2 选 canonical，merged_from 全量留痕、被合并
  条目以 merged_into 保留绝不静默删除；字段矛盾逐条入冲突台账并给规则编号
  R1..R6，裁决不了的一律升级人工复核不猜测；输入标注仅作 provenance 提示，
  指纹独立验证并显式说明结论与标注是否一致；合并后的 canonical 集合仍逐条
  做三态筛选（保留/待定/排除，带原文引用）；空候选集、缺元数据、无法解析
  记录、接口异常全部显式入账。
---

# dedup-conflict-adjudicator：去重指纹 + 版本合并 + 冲突裁决 + 人工复核升级

## 适用场景与边界

- 适用：给定研究问题 + 有限候选文献快照，快照中**可能包含重复导出、版本
  变体（预印本↔正式版）、字段矛盾的同成果记录、以及被标注为“合成重复
  导出/冲突意见”的输入夹具**。技能交付一个可审计的判定系统：每个候选对的
  相似度分解可查、每个合并/排除/升级决定有规则编号与理由、每条原始记录
  在结果中恰好出现一次。
- 边界（**不做**）：不联网检索补充证据、不臆造缺失元数据（缺摘要/年份/
  作者只入账 `metadata_gaps`）、不把输入夹具标注当作裁决依据（仅作
  provenance 提示保留，结论与标注一致/不一致都写明）、不静默删除任何记录
  （被合并者以 `merged_into` 保留在台账）、不猜测无法裁决的冲突（一律升级
  人工复核）、不与任何其他 skill 共享代码（独立目录、独立脚本）。
- 核心失败模式防御：基础 Agent 的典型错误是“看到两篇同题就删一篇”“夹具
  标注重复就直接合并”“字段矛盾随手取一个”“疑似对吞掉不留痕”。本 Skill
  把一切可机械判定的部分（指纹、阈值档、合并留痕、覆盖率校验）交给确定性
  脚本，模型只做两类裁决：疑似簇的确证/推翻、冲突的裁决或升级——且每条
  裁决写入 `adjudications.jsonl` 留痕。

## 运行环境

- 三个 Python 3 **标准库**脚本，位于 `scripts/`：`normalize.py`、
  `dedup_engine.py`（子命令 fingerprint / conflicts / merge / queue）、
  `assemble.py`，均有 `--help`，校验失败以非零退出。无第三方依赖，无需
  网络。
- 默认安装路径 `/skills/weekly-skill`；若不在，先定位：

  ```bash
  SKILL_DIR=/skills/weekly-skill
  [ -f "$SKILL_DIR/scripts/dedup_engine.py" ] || \
    SKILL_DIR=$(dirname "$(dirname "$(find / -maxdepth 5 -path '*/scripts/dedup_engine.py' 2>/dev/null | head -1)")")
  python3 "$SKILL_DIR/scripts/dedup_engine.py" --help
  ```

- 预算纪律：模型请求有限。指纹、聚类、冲突扫描、合并、组装全部一次跑完；
  模型只读脚本产物（`clusters.json`、`conflict_ledger.json`、
  `pairs.jsonl`），写两个裁决文件（`adjudications.jsonl`、
  `screening.jsonl`），再触发 merge → queue → assemble。

## 工作流程（八步）

### 1. 读材料，固证

- 读 `/input/case.json` 与 `task.md`，提取 `case_id`、研究问题、
  `output_contract`（缺省时按第 8 步默认合同）。**读真实文件**，不臆测。
- 识别输入夹具标注（如 `_label`/`fixture`/`annotation` 中的“合成重复导出/
  冲突意见”字样）：记录其存在，但按规则 **R5**，仅作 provenance 提示。

### 2. 归一化并立即脚手架（先保底）

```bash
mkdir -p /app/work /app/output
python3 "$SKILL_DIR/scripts/normalize.py" \
    --case /input/case.json --task task.md --work /app/work --out /app/output
```

- 输出 `/app/work/records.jsonl`（稳定 `record_id`、title、abstract、
  authors、year、venue、doi、url、`provenance_note`、`source_keys`）、
  `/app/work/case_meta.json`、以及 `status="partial"` 的
  `/app/output/result.json` 骨架。此后每步就地更新，诚实优先于完整。

### 3. 指纹与聚类（脚本，确定性）

```bash
python3 "$SKILL_DIR/scripts/dedup_engine.py" fingerprint --work /app/work
```

- 输出 `pairs.jsonl`：每个候选对的相似度分解（title_jaccard、
  author_overlap、year_diff、doi_match、title_fp_equal、
  first_author_year_match）与判定档（confirmed_duplicate /
  version_variant / suspected_duplicate / independent，阈值见 R1）。
- 输出 `clusters.json`：确证重复簇、版本变体簇、疑似对清单（疑似对
  **只进复核队列，不自动合并**）。

### 4. 冲突扫描（脚本）

```bash
python3 "$SKILL_DIR/scripts/dedup_engine.py" conflicts --work /app/work
```

- 输出 `conflict_ledger.json`：重复组内字段矛盾（year/venue/authors/doi，
  按 R3 给建议裁决与是否升级）、以及 R5 条目（夹具标注与指纹结论不一致）。
  每条冲突带规则编号、双方原值、建议裁决值或“升级人工复核”。

### 5. 模型裁决（唯一需要判断的环节之一）

读 `clusters.json` 与 `conflict_ledger.json`，写
`/app/work/adjudications.jsonl`，每行一条：

```json
{"ids": ["R004", "R005"], "decision": "confirm_merge", "canonical_hint": "R004", "reason": "同题同作者同年，仅 venue 不同，为版本变体，正式版作 canonical"}
{"ids": ["R006", "R007"], "decision": "reject_merge", "reason": "标题仅词面相近，作者与年份均不同，独立研究"}
{"ids": ["R001", "R002"], "decision": "escalate", "reason": "同 DOI 两导出年份矛盾，快照无法裁决，升级人工"}
```

- 纪律：确认合并必须能引用 `pairs.jsonl` 中的相似度信号；推翻脚本建议
  （reject_merge）必须写明反证；**裁决不了就 escalate，不猜**。没有把握
  的疑似对可整组不写，脚本会将其留在复核队列（R4）。

### 6. 合并（脚本，含 R6 完整性校验）

```bash
python3 "$SKILL_DIR/scripts/dedup_engine.py" merge \
    --work /app/work --adjudications /app/work/adjudications.jsonl
python3 "$SKILL_DIR/scripts/dedup_engine.py" queue --work /app/work
```

- `merge` 输出 `canonical.jsonl`（canonical 选择顺序：正式同行评审版 >
  预印本 > 元数据完整度高 > 年份新 > record_id 序，见 R2）与
  `merge_map.json`（`merged_into` 映射 + 簇清单）。R6 校验：每条原始记录
  恰好在 canonical 或某个 `merged_from` 中出现一次，不过则非零退出。
- `queue` 输出 `review_queue.json`：未决疑似对、升级的冲突、无法解析记录、
  缺标题记录。

### 7. 轻量筛选裁决（模型，对 canonical 集合）

对 `canonical.jsonl` 每条，按研究问题写 `/app/work/screening.jsonl`：

```json
{"record_id": "R003", "label": "retained", "quote": "…摘要原文子串…", "evidence_field": "abstract", "confidence": "high", "reason": "对照研究问题逐条命中"}
```

- label ∈ {retained, pending, excluded}；`quote` 必须是该条 title 或
  abstract 的原文子串（≥8 字符，assemble 回验，防臆造证据）；缺摘要者用
  标题子串并标 `evidence_field: "title"`；信息不足一律 `pending` 并说明
  缺什么。

### 8. 校验与组装交付物

```bash
python3 "$SKILL_DIR/scripts/assemble.py" --work /app/work --out /app/output
```

- 校验（任一失败非零退出，骨架 `result.json` 保留 `partial`，不交付假象）：
  V1 筛选覆盖率、V2 裁决 schema 与引用回验、V3 原始记录恰好出现一次、
  V4 合同字段齐。
- 产出 `/app/output/result.json`（合同字段 + `dedup_map`、`conflicts`、
  `ranked_results`、`metadata_gaps`、`review_queue`、`sources`、
  `uncertainty`、`change_log`、诚实 `status`：complete /
  complete_with_open_review / empty_result / partial）与
  `/app/output/adjudication_report.md`（簇表、合并理由、冲突裁决表、
  人工复核队列、筛选裁决表）。

## 输出合同缺省

若 `case.json` 未给出 `output_contract`，`result.json` 至少包含：
`case_id`、`status`、`research_question`、`counts`（total/canonical/
merged/retained/pending/excluded）、`ranked_results`、`dedup_map`
（`merged_into`、`clusters`、`rejected_pairs`）、`conflicts`、
`review_queue`、`metadata_gaps`、`uncertainty`、`sources`、`change_log`。
若合同给出字段清单，以合同为准并保留上述审计字段；合同字段无法产出时
写 `PENDING::` 占位并告警，绝不编造。

## 自查清单（交付前逐项确认）

- [ ] `assemble.py` 退出码为 0；V1..V4 全过；
- [ ] 每条原始记录在结果中恰好出现一次（canonical 或 merged_from 成员）；
- [ ] 被合并条目均在 `dedup_map.merged_into` 中可回溯，无静默删除；
- [ ] 每条冲突有规则编号 R1..R6、双方原值、裁决值或升级标记；
- [ ] 夹具标注仅出现在 provenance_note / 报告说明中，未作裁决依据；
- [ ] 无法裁决的对与冲突全部在 `review_queue`，无猜测；
- [ ] `status` 与实际完成度一致；`adjudication_report.md` 可供未参与者
      逐条复核。

## 最小调用示例（示意，非案例答案）

```bash
# 已跑完第 2、3、4 步后，模型只写两个裁决文件：
cat > /app/work/adjudications.jsonl <<'EOF'
{"ids":["R002","R003"],"decision":"reject_merge","reason":"标题词面相近但作者、年份均不同"}
EOF
cat > /app/work/screening.jsonl <<'EOF'
{"record_id":"R001","label":"retained","quote":"double-blind randomized trial","evidence_field":"abstract","confidence":"high","reason":"设计与人群均命中研究问题"}
EOF
python3 "$SKILL_DIR/scripts/dedup_engine.py" merge --work /app/work \
    --adjudications /app/work/adjudications.jsonl \
  && python3 "$SKILL_DIR/scripts/dedup_engine.py" queue --work /app/work \
  && python3 "$SKILL_DIR/scripts/assemble.py" --work /app/work --out /app/output
```

示例中的记录与引用均为虚构示意，正式运行必须以真实快照为准。
