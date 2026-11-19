---
name: prisma-repro-screening
description: 文献综述生成的"筛选优先"协议。当任务给出一批真实文献与一个具体研究问题，要求完成可复现的文献筛选（纳入/排除）、去重、两轮筛序并产出综述、趋势或选题评估时使用。核心机制：先把纳入/排除标准写成编号条款（IC1…/EC1…）并保存，再逐篇做出可引用标准编号的筛选决定；去重显式分组；PRISMA 式流程数字一律由脚本从筛选日志推导，不得手写；每篇被排除的文献都留有理由。适用于任何学科的系统筛选与综述任务；不负责单篇精读、全文翻译与语言润色。
---

# prisma-repro-screening：筛选优先的可复现文献综述

## 1. 本 Skill 解决什么问题

综述生成最常见的系统性错误发生在动笔之前：**筛选标准从未写明**，或写在读完结论之后；排除决定没有理由；去重凭感觉；PRISMA 数字与筛选日志对不上。本 Skill 把筛选做成可复跑的数据流：

1. **标准先行**：先写编号纳入/排除标准（IC1…/ECn…/EC1…/ECm…）并落盘，之后才能读结论、做归纳；标准条款直接绑定研究问题的措辞。
2. **逐篇留痕**：每篇文献的每个决定都是 `{decision, criteria_ids, reason}` 记录，排除必须引用至少一条标准编号。
3. **数字脚本推导**：PRISMA 流程图/表中的各阶段计数全部由 `scripts/prisma_flow.py` 从筛选日志计算；手写数字与日志不一致即报错。
4. **去重显式**：疑似重复的文献组成分组，明确保留代表篇、标记其余为 `duplicate_of`，禁止静默丢弃。

## 2. 适用条件与不适用范围

适用：给定文献集合（PDF/文本，可含仅摘要、缺元数据、重复条目）与研究问题，要求筛选后综述、趋势分析、选题评估或证据图绘制的任务。

不适用：单篇精读、全文翻译、润色、选刊、审稿式事实核查。本 Skill 的重心是"筛选可复现 + 在其上生成有定位引用的综述"，与单篇审查类任务互补。

## 3. 输入契约（运行时防御式解析）

Harbor 运行契约：输入 `/input/case.json` + `/input/task.md`；材料由 case 指定或在 `/input/` 下发现；工作 `/app/work`；交付 `/app/output/`。**不假设字段名**：

1. `case_id`：依次 `case_id`/`caseId`/`id`；缺失时用文件名并记入 uncertainties。
2. 研究问题：递归查找 `research_question`/`question`/`topic`/`title`/`objective`；再读 task.md。task.md 的具体要求优先于本文件通用流程。
3. 文献清单：递归查找 `documents`/`papers`/`references`/`files`/`literature`/`corpus`/`materials`；元素可为路径字符串或含 `path`/`file`/`pdf`/`title` 等键的字典；都不命中则在 `/input/` 下按 `*.pdf → *.txt → *.md → *.html` 收集。URL 条目无本地文件记 `metadata_only`。
4. `output_contract`：递归查找 `output_contract`/`contract`/`output_fields`/`required_fields`；`build_result.py` 逐字段 mirror 进 result.json。

零文献 / 全部解析失败：照常写出 `status="blocked"` 的 result.json 与说明，不得空跑。

## 4. 运行方式（总览）

```bash
S=<skills 目录>/prisma-repro-screening/scripts
python3 $S/run_case.py init --case /input/case.json --task /input/task.md --input-dir /input --work /app/work --out /app/output
# 阶段1(模型): 写 /app/work/criteria.md → 逐篇填写 /app/work/screening_log.json
python3 $S/run_case.py audit --work /app/work --out /app/output
# 阶段2(模型): 对 included 文档做摘要/证据表/草稿(见第5节)
python3 $S/run_case.py finalize --case /input/case.json --work /app/work --out /app/output
```

`init` 在 10 秒内产出第一版 partial result.json（`status=in_progress`）。`audit` 校验筛选日志的完备性与一致性，输出 `/app/output/audit_report.json`；不通过时按报告修复后再 `audit`，最多两轮，之后带降级说明进入 finalize。

## 5. 工作流程

总预算：64 次模型请求、900 秒、单次响应 ≤16384 token（含推理）。脚本不占模型预算。中间产物每阶段落盘。

### 阶段 0：解析与去重（脚本，`init`，0 次模型请求）

- `ingest.py`：防御式解析、材料发现、逐文档文本抽取（`pdftotext -layout` → pypdf → 纯文本回退；记录方法与失败原因）、SHA-256 留痕、分级（`fulltext`/`abstract_only`：可用正文 <300 词/`failed`）。
- `dedup.py`：标题归一化（小写、去标点、折叠空白）精确哈希 + 前 40 字符前缀哈希两组疑似重复分组；同组文献在筛选日志中必须有一行 `duplicate_of` 决定或全部独立纳入并在理由中说明为何不算重复（如会议版与期刊版实质不同）。
- 产物：`docs.jsonl`、`pages/<doc_id>.jsonl`、`dup_groups.json`、`extract_meta.json`、partial result.json。

### 阶段 1：标准先行与两轮筛选（模型，随后 `audit` 脚本校验）

**顺序硬约束**：先写 `/app/work/criteria.md`（模板 `templates/screening_log.md`）：

- 研究问题分解为 2–4 个可判定方面（对象/干预或方法/结局或指标/场景）。
- 纳入标准 IC1…ICn：每条一句话、可判定、措辞来自研究问题；标注每条需要题录级还是全文级信息。
- 排除标准 EC1…ECm：常见情形——非原始研究（综述/社论）、对象不符、无相关结局、会议摘要无数据、重复发表、全文不可用且摘要不满足 IC 全部条款。
- 仅摘要文献**不得仅因无全文被排除**；只有当摘要信息无法满足任一 IC 条款判定为 include 时才按相应 EC 排除，并在理由中写明缺的是哪条 IC 所需信息（见 `rules/abstract_only_policy.md`）。

然后写 `/app/work/screening_log.json`：

```json
{"phase":"title_abstract","records":[
 {"doc_id":"D1","decision":"include","criteria_ids":["IC1","IC3"],"reason":"摘要明确报告 Y 任务性能对比"},
 {"doc_id":"D2","decision":"exclude","criteria_ids":["EC2"],"reason":"研究对象为 Z 而非 Y"},
 {"doc_id":"D3","decision":"duplicate_of","criteria_ids":[],"reason":"与 D1 同标题同作者, 保留 D1","representative":"D1"}]},
 "phase":"fulltext","records":[{"doc_id":"D1","decision":"include","criteria_ids":["IC1","IC3"],"reason":"全文确认实验设置满足 IC3"}]}
```

- 两轮筛选：第一轮题录/摘要，第二轮仅对第一轮 include 的文献做全文复核。
- `audit` 校验：criteria.md 存在且非空；每篇文档在两轮中都有决定；`decision ∈ {include, exclude, duplicate_of}`；exclude 必须引用 ≥1 条 EC 或"IC 无法满足"编号并写明缺哪条信息；duplicate_of 必须给出 representative 且 representative 本身为 include；无重复组漏处理；PRISMA 计数与记录数一致。

### 阶段 2：证据表与综述草稿（模型 3–8 次 + `prisma_flow.py`）

1. 对最终 included 文档写 `/app/work/digests/<doc_id>.md`（对象/数据、方法、核心结论带页码 `p<页>`、关键数字、局限）。
2. 从 digest 归纳主题，写 `/app/work/themes.md`（主题必须指回文献簇，禁套通用模板；标出冲突主题）。
3. 写证据表 `/app/work/evidence_table.jsonl`：`{evidence_id, doc_id, page, excerpt, claim, theme, polarity(positive|negative|null), strength}`；excerpt 为逐字摘录；每个主题至少检查一次反面证据，polarity=negative 的行不得省略。
4. 写 `/app/output/review_draft.md`：按主题组织；实质句挂证据标记 `[E#]`；冲突证据并陈不调和；缺口具体化；中文书面语。
5. `python3 $S/run_case.py finalize`：生成 PRISMA 流程（`audit_report`/`prisma_flow.md`/`prisma_flow.json` 由 finalize 内部调用 `prisma_flow.py`），组装 result.json。

## 6. 异常处置（写入 uncertainties）

- **零可用文献**：`status="blocked"`，PRISMA 各阶段计数为 0，说明照常交付。
- **全部仅摘要**：筛选照常两轮进行（第二轮以摘要代替全文并在日志标注）；综述强度整体封顶 `suggestive`。
- **元数据缺失**：以文件名/case 信息标识，标记 `metadata_incomplete`，不猜测补齐。
- **结论冲突**：主题标 `contested`，双方证据行并存；不取平均。
- **研究问题超出语料**：结论收缩到语料覆盖范围，缺口入 uncertainties。

## 7. 默认输出结构（output_contract 缺失时）

```json
{
  "case_id": "…",
  "status": "completed|partial|blocked",
  "research_product": {"question":"…","draft":"review_draft.md 全文","themes":[…],"bottom_line":"…"},
  "screening_log": {"criteria_md":"…","decisions":[…],"prisma_flow":{"identified":N,"after_dedup":N,"title_abstract_included":N,"fulltext_included":N,"excluded_with_reasons":N}},
  "evidence_matrix": [{"evidence_id":"E1","doc_id":"D1","page":3,"excerpt":"…","claim":"…","theme":"…","polarity":"positive","strength":"suggestive"}],
  "uncertainties": ["…"],
  "sources": [{"doc_id":"D1","path":"…","sha256":"…","tier":"…","extract_method":"…"}],
  "change_log": ["…"]
}
```

若 case 提供 `output_contract`，逐字段 mirror；无对应内容填 `null` 并在 uncertainties 说明，**不得漏字段**。

## 8. 文件清单

- `scripts/run_case.py`：init / audit / finalize 编排。
- `scripts/ingest.py`：防御式解析、材料发现、文本抽取、分级。
- `scripts/dedup.py`：标题归一化与重复分组。
- `scripts/screen_check.py`：筛选日志完备性审计（criteria 先行、逐篇决定、理由引用编号、重复组闭合、计数一致）。
- `scripts/prisma_flow.py`：从筛选日志推导流程计数与流程表。
- `scripts/build_result.py`：result.json 组装与 output_contract 镜像。
- `rules/criteria_protocol.md`、`rules/abstract_only_policy.md`：标准写法与仅摘要政策。
- `templates/screening_log.md`、`templates/prisma_flow.md`：筛选日志与流程表模板。
- `examples/example_walkthrough.md`：示意流程（合成示例）。
