---
name: prisma-screen-ledger
description: >-
  文献筛选与智能排序——协议化双门三态筛选与判定台账。当任务给出明确研究问题
  （或查询意图）与一份有限候选文献快照，要求对全部条目逐条做相关性判断、分层
  标签（保留/待定/排除）与可追溯排序时触发。差异化能力：从研究问题派生
  可判定的纳入/排除标准（PICOS 式），题录门→摘要门两段筛选，每条裁决必须
  绑定标准编号、摘要原文引用与置信度；确定性脚本校验覆盖率 100%、引用
  确为原文子串（防臆造证据）、三层台账对账，校验不过不交付；空候选集、
  缺摘要/年份、疑似重复、快照标注冲突等异常全部显式入账。
---

# prisma-screen-ledger：协议化双门三态筛选与判定台账

## 适用场景与边界

- 适用：给定研究问题 + 候选文献快照（题录/摘要级元数据），对**每一条**候选
  完成相关性判断、三态标签与可追溯排序，交付结构化 `result.json` 与可人工
  复核的筛选报告。快照是有限证据集，技能的全部判断只依据快照内证据。
- 边界（**不做**）：不联网检索补充证据、不声称全局召回、不阅读快照外全文、
  不臆测摘要中不存在的研究设计细节、不学习式打分（排序只按三态分层与
  确定性键，见“排序约定”）、不删除任何候选记录（疑似重复仅打标记，
  保留完整性）。
- 核心失败模式防御：基础 Agent 的典型错误是“标题有关键词即相关”的
  词面误判、排除后无说明、待定滥用、排序不稳定、引用无法回溯原文。本
  Skill 把一切可机械校验的部分（覆盖率、引用子串、台账对账、排序确定
  性）交给脚本，模型的判断空间被约束在“对照标准裁决 + 引用原文”，且
  引用被脚本逐条回验。

## 运行环境

- 两个 Python 3 **标准库**脚本，位于 `scripts/`：`prepare.py`、`ledger.py`，
  均有 `--help`，任何校验失败以非零退出。无第三方依赖，无需网络。
- 默认安装路径 `/skills/weekly-skill`；若不在，先定位：

  ```bash
  SKILL_DIR=/skills/weekly-skill
  [ -f "$SKILL_DIR/scripts/ledger.py" ] || \
    SKILL_DIR=$(dirname "$(dirname "$(find / -maxdepth 5 -path '*/scripts/ledger.py' 2>/dev/null | head -1)")")
  python3 "$SKILL_DIR/scripts/ledger.py" --help
  ```

- 预算纪律：模型请求有限。`prepare.py` 一次跑完归一化，模型只读标准与
  快照、做裁决并写 `decisions.jsonl`、读校验结果、组装交付物。

## 工作流程（八步）

### 1. 读材料，固证

- 读 `/input/case.json` 与 `task.md`，提取 `case_id`、研究问题（候选键：
  `research_question` / `question` / `query` / `task` / `objective`）、
  输出合同（`output_contract` 字段清单，缺省时按第 8 步默认合同）。
- **读真实文件**，不臆测来源内容。记录材料清单（文件名+用途）备用，
  最终写入 `result.json` 的 `sources`。

### 2. 归一化候选集并立即脚手架（先保底）

```bash
mkdir -p /app/work /app/output
python3 "$SKILL_DIR/scripts/prepare.py" \
    --case /input/case.json --task task.md --work /app/work --out /app/output
```

- 输出：`/app/work/records.jsonl`（每条候选：稳定的 `record_id`、title、
  abstract、authors、year、venue、doi、url、来源键）、
  `/app/work/case_meta.json`（case_id、研究问题、合同字段、记录数）。
- `prepare.py` 同时生成 `PENDING::*` 的 `/app/output/result.json` 骨架，
  `status="partial"`。此后每完成一步就地更新，**诚实优先于完整**。

### 3. 派生筛选标准（PICOS 式，一次成文）

依据 `case_meta.json` 的研究问题，在 `/app/work/criteria.json` 写出
纳入标准 `I1..In` 与排除标准 `E1..Em`（模板见
`references/label_system.md`）。纪律：

- 每条标准必须**单条可判定**，写明判定所需字段（标题/摘要/年份/来源）。
- 标准编号成文后**不再增删**；执行中发现的模糊情形写入
  `/app/work/change_log.md`（时间+内容+理由），不得静默改标准。
- 标准只覆盖快照可见证据；依赖快照外信息（如全文方法细节）的标准
  禁用，相关不确定性进“待定”理由。

### 4. Gate-1 题录门（只据标题+元数据）

- 每条候选先过 Gate-1：`E` 标准明显命中（如研究对象/物种/时期不符）
  → `excluded`，记 `E#` 与标题证据；信息不足判断 → 进 Gate-2。
- **禁止**在 Gate-1 做“保留”裁决；只有 Gate-2 能出“保留”。

### 5. Gate-2 摘要门（逐条对照，三态裁决）

- Gate-2 裁决规则（写死，见 `references/label_system.md`）：
  所有纳入标准命中且无排除命中 → `retained`；任一排除命中 →
  `excluded`；摘要缺失或关键维度信息不足 → `pending`（**待定是合法
  终态**，但理由必须说明缺什么信息、需要什么材料才能改判）。
- 每条裁决的 `quote` 必须是该条 title/abstract 的**原文子串**（脚本回验）。
  无摘要可用标题子串并注明 `evidence_field`。
- 置信度三档：`high`（直接证据）、`medium`（间接推断）、`low`
  （词面冲突需人工复核），写入 `confidence`。
- 将裁决写入 `/app/work/decisions.jsonl`，每行一条：

  ```json
  {"record_id": "R003", "label": "excluded", "criteria": ["E2"],
   "criteria_missed": ["I3"], "quote": "…摘要原句…", "evidence_field": "abstract",
   "confidence": "high", "reason": "研究对象为小鼠，非目标人群"}
  ```

### 6. 台账校验（脚本，不过不交付）

```bash
python3 "$SKILL_DIR/scripts/ledger.py" check \
    --work /app/work --out /app/output
```

校验项（任一失败非零退出，模型必须修复后重跑）：

1. 覆盖率：records.jsonl 中每条 record_id 在 decisions.jsonl 恰好出现一次；
2. schema：label ∈ {retained,pending,excluded}，criteria 非空、编号存在于
   criteria.json，confidence 合法，reason 非空；
3. 引用回验：quote 是 해당记录 title 或 abstract 的子串（长度 ≥ 8 字符）；
4. 台账对账：retained + pending + excluded = 候选总数；
5. 待定纪律：pending 条目的 reason 含缺失信息说明（启发式检查：长度 ≥ 10
   字符或含“缺/不足/无法判断”类标记）。

### 7. 异常与冲突处理（显式入账，不静默跳过）

- 空候选集：decisions.jsonl 为空即合法；result.json 记
  `status="empty_result"`，`counts` 全 0，说明原因，照常交付。
- 缺摘要 / 缺年份 / 缺作者：不补造；`metadata_gaps` 列表逐条记录
  record_id 与缺失字段，相关裁决按信息不足规则处理。
- 疑似重复（同题异源/预印本与正式版同现）：不删除、不合并，打
  `duplicate_suspect` 标记并在报告中给出证据；完整性优先。
- 快照内标注冲突（如同一记录两个来源字段互相矛盾、或输入夹具声明
  “合成重复导出”）：两者都保留原样记录，冲突进 `conflicts` 列表，
  说明“输入标注为夹具提示，不作为裁决依据”。
- 权限 / 接口 / 解析异常：不伪造数据；记 `status="partial"` 与失败原因，
  已完成的裁决照常交付。

### 8. 组装交付物

```bash
python3 "$SKILL_DIR/scripts/ledger.py" assemble \
    --work /app/work --out /app/output
```

产出（`/app/output/`）：

- `result.json`：含 `case_id`、合同要求的全部字段、三态计数、按“排序约定”
  排序的逐条结果（label、record_id、criteria、quote、confidence、
  reason、metadata_gaps）、`sources`、`uncertainty`、`conflicts`、
  `change_log`、`status`。
- `screening_report.md`：研究问题、标准全文、Gate-1/2 统计、逐条裁决
  表（引用+理由）、异常与冲突清单、待人工复核项——人工审核者凭此
  报告即可逐条复核定案。
- `criteria.json`、`decisions.jsonl` 一并复制到输出目录，供复核人重跑
  `ledger.py check` 独立验证。

## 排序约定（确定性，无学习）

总次序 = 分层（retained > pending > excluded）→ 层内按 confidence
（high > medium > low）→ 层内按 year 新→旧（缺失年份排最后）→
`record_id` 字典序。同分同档不改写相对次序；换一批候选集时，同一记录的
相对位置只由上述键决定，保证可复现。

## 输出合同缺省

若 `case.json` 未给出 `output_contract`，`result.json` 至少包含：
`case_id`、`research_question`、`counts`（retained/pending/excluded/
total）、`ranked_results`（全部候选，含上述逐条字段）、`metadata_gaps`、
`conflicts`、`uncertainty`、`sources`、`status`。若合同给出字段清单，
以合同为准并保留上述审计字段。

## 自查清单（交付前逐项确认）

- [ ] 候选总数 = 三态之和，脚本 check 通过；
- [ ] 每条裁决有标准编号 + 原文子串引用 + 理由 + 置信度；
- [ ] 无摘要/年份/作者的记录已列入 metadata_gaps，未补造；
- [ ] 疑似重复仅标记未删除，冲突未静默消解；
- [ ] 快照标注/夹具提示未被当作裁决证据；
- [ ] `status` 与实际完成度一致（partial 已注明缺失部分）；
- [ ] screening_report.md 可供未参与本任务的人逐条复核。

## 最小调用示例（示意，非案例答案）

```bash
# 已按第 2 步生成 /app/work 后，模型只写裁决文件：
cat > /app/work/decisions.jsonl <<'EOF'
{"record_id":"R001","label":"retained","criteria":["I1","I2"],
 "criteria_missed":[],"quote":"randomized trial in adults with hypertension",
 "evidence_field":"abstract","confidence":"high","reason":"人群、设计均命中"}
{"record_id":"R002","label":"excluded","criteria":["E1"],
 "criteria_missed":["I1"],"quote":"in murine models","evidence_field":"abstract",
 "confidence":"high","reason":"E1 排除：研究对象为小鼠"}
EOF
python3 "$SKILL_DIR/scripts/ledger.py" check --work /app/work --out /app/output \
  && python3 "$SKILL_DIR/scripts/ledger.py" assemble --work /app/work --out /app/output
```

示例中的引用与题录均为虚构示意，正式运行必须以真实快照为准。
