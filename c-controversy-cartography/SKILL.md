---
name: controversy-gap-cartography
description: 文献综述生成的"冲突与空白制图"协议。当任务要求在一批真实文献上归纳主题、写综述草稿，且评审关注反面证据、结论分歧与研究空白是否被忠实保留时使用。核心机制：用语料自身的对象/方法/结论特征聚类出主题（拒绝套用背景/方法/挑战/展望模板），为每篇文献抽取带定位的候选论断并由模型裁定为正向/负向/中性，脚本扫描同主题内方向相反或数值冲突的论断对生成矛盾矩阵，再由证据分布（单源主题、未裁决冲突、覆盖缺口）推导空白图；综述按"主张—证据—反证—缺口"结构逐主题成文。适用于任何学科的综述、趋势分析、选题评估；不负责单篇精读、翻译与润色。
---

# controversy-gap-cartography：冲突证据与研究空白制图

## 1. 本 Skill 解决什么问题

多数综述草稿死于同一个病根：**模板先于语料**。不管拿到什么文献都写"背景—方法—挑战—展望"，主题之间互相重叠，反面证据被平均掉，结尾用"有待进一步研究"敷衍。本 Skill 的综述结构完全由语料决定：

1. **主题从语料长出**：用文献自身的词项分布聚类，聚类结果就是主题候选；主题名由模型依据簇内文献命名，且必须能指回具体文献簇。
2. **论断带方向**：每篇文献的候选论断句（含结果谓词或数值的句子）被抽取并带页码定位，模型裁定为正向/负向/中性；方向是后续一切综合的输入。
3. **矛盾显式成图**：脚本扫描同一主题内方向相反、或同一指标数值冲突的论断对，生成矛盾矩阵；模型裁决"条件差异可否解释冲突"，不能解释的标 `unresolved_conflict`。
4. **空白落到证据缺口**：研究空白只能从证据分布里长出来——单源主题、未裁决冲突、人群/场景覆盖缺失——每个空白绑定具体缺口描述，禁止套话收尾。

## 2. 适用条件与不适用范围

适用：给定文献集合（PDF/文本，可含仅摘要、缺元数据、重复条目）与研究问题，要求主题归纳、综述草稿、趋势分析或选题评估的任务。

不适用：单篇精读、翻译、润色、选刊、审稿式核查。本 Skill 不替代人对研究价值的判断，只保证综述结构忠实于语料证据分布。

## 3. 输入契约（运行时防御式解析）

Harbor 运行契约：输入 `/input/case.json` + `/input/task.md`；材料由 case 指定或在 `/input/` 下发现；工作 `/app/work`；交付 `/app/output/`。**不假设字段名**：

1. `case_id`：依次 `case_id`/`caseId`/`id`；缺失时用文件名并记入 uncertainties。
2. 研究问题：递归查找 `research_question`/`question`/`topic`/`title`/`objective`；再读 task.md。task.md 要求优先。
3. 文献清单：递归查找 `documents`/`papers`/`references`/`files`/`literature`/`corpus`/`materials`；元素可为路径或含 `path`/`file`/`pdf`/`title` 的字典；都不命中则在 `/input/` 下按扩展名收集（`*.pdf → *.txt → *.md → *.html`）。URL 无本地文件记 `metadata_only`。
4. `output_contract`：递归查找 `output_contract`/`contract`/`output_fields`/`required_fields`；`build_result.py` 逐字段 mirror 进 result.json。

零文献 / 全部解析失败：照常写出 `status="blocked"` 的 result.json 与说明。

## 4. 运行方式（总览）

```bash
S=<skills 目录>/controversy-gap-cartography/scripts
python3 $S/run_case.py init --case /input/case.json --task /input/task.md --input-dir /input --work /app/work --out /app/output
# 模型阶段（第5节）: claims.jsonl → themes.md → controversy_matrix.md → gaps.md → review_draft.md
python3 $S/run_case.py check --work /app/work --out /app/output
python3 $S/run_case.py finalize --case /input/case.json --work /app/work --out /app/output
```

`init` 在 10 秒内产出 partial result.json。`check` 做结构一致性校验（主题覆盖全部文档、论断定位可解析、矛盾矩阵与空白图引用的论断存在、草稿的 `[E#]`/`[C#]`/`[G#]` 标记闭合）；`finalize` 组装终版。

## 5. 工作流程

总预算：64 次模型请求、900 秒、单次响应 ≤16384 token（含推理）。脚本不占模型预算。产物每阶段落盘 `/app/work/`。

### 阶段 0：解析与论断抽取（脚本，`init`，0 次模型请求）

- `ingest.py`：防御式解析、材料发现、文本抽取（`pdftotext -layout` → pypdf → 纯文本回退）、SHA-256 留痕、分级（`fulltext`/`abstract_only`/`failed`）。
- `extract_claims.py`：从每篇抽取**候选论断句**——含结果谓词（improve/reduce/outperform/significant/demonstrate/表明/提升/降低/优于/显著……）或数值的句子——带 `p<页>.¶<段>` 定位，写 `claims_candidates.jsonl`。这是模型的阅读索引：语料大时优先读候选句所在页，不得跳过结论段。
- `cluster_themes.py`：按文档词项向量（去停用词）余弦相似度连通聚类（阈值 0.25），输出 `theme_scaffold.json`：每个簇的文档列表、簇内高频词、规模。聚类只是脚手架：模型必须检查簇的语义一致性，必要时在 `themes.md` 中调整（拆分/合并），并给出每个主题的一句话边界。
- 产物：`docs.jsonl`、`pages/<doc_id>.jsonl`、`claims_candidates.jsonl`、`theme_scaffold.json`、partial result.json。

### 阶段 1：论断裁定与主题命名（模型，1 次/簇 + 1 次/篇批）

写 `/app/work/claims.jsonl`（每行）：

```json
{"claim_id":"C1","doc_id":"D1","anchor":"p3.¶2","statement":"域内 F1 提升 4.1 点","direction":"positive|negative|neutral","topic_hint":"域内性能","metric":"F1","value":"+4.1"}
```

- 只收录候选句中确实是结果论断的条目；direction 按论断对研究问题的含义裁定（负面结果、局限、无效结论都是 `negative`）。
- 写 `/app/work/themes.md`：主题编号 T1…、名称、边界一句话、文档列表、与该主题无关的文档排除说明。主题必须覆盖全部可筛文档（misc 桶只放真正无法归类的）。

### 阶段 2：矛盾矩阵与空白图（脚本 + 模型）

1. `contradiction_scan.py`：同主题内 direction 相反（positive vs negative）或同 metric 数值冲突的论断对 → `controversy_candidates.json`。模型逐对裁决，写 `/app/work/controversy_matrix.md`：每对给 `C#`/`C#`、冲突点一句话、可否由对象/条件/方法差异解释；不可解释标 `unresolved_conflict`，可解释写明解释并降级为 `explained`。
2. `gap_map.py`：从证据分布推导空白候选：单源主题（仅 1 篇）、未裁决冲突、`negative` 论断集中的主题、明显缺失的对比维度 → `gap_candidates.json`。模型逐条写成 `/app/work/gaps.md`：`{gap_id, theme, type, statement, evidence_deficit}`；statement 必须引用触发该空白的具体证据（如"仅 D1 报告跨域结果，且无第三方复现"），禁止无证据挂帅的展望。

### 阶段 3：草稿与校验（模型 + `check` + `finalize`）

写 `/app/output/review_draft.md`（结构见 `templates/theme_map.md` 与 `rules/synthesis_topology.md`）：

- 按主题分节，每节固定顺序：**主题陈述（边界）→ 主张与证据（positive 先行，挂 `[C#]`）→ 反证与分歧（negative 与 `unresolved_conflict` 并陈，挂 `[C#] [X#]`）→ 空白（挂 `[G#]`）**。
- 每个主题给出**共识梯度**：`已确立`（多源且方向一致）/ `有提示`（单源或仅摘要）/ `有争议`（存在未裁决冲突）。
- 中文书面语；数值必须来自 `[C#]` 论断；结尾的综合结论按各主题共识梯度给出有层次的回答，而不是单线叙事。

随后 `run_case.py check`（结构校验）与 `run_case.py finalize`（组装 result.json）。`check` 失败时修复对应产物重跑，最多两轮。

## 6. 异常处置（写入 uncertainties）

- **仅摘要文献**：候选句只来自摘要；其论断 direction 保留但主题共识梯度封顶 `有提示`。
- **元数据缺失**：以文件名/case 信息标识，标记 `metadata_incomplete`，不猜测补齐。
- **全部文档聚成一类**：允许（语料高度同质）；此时主题划分改为按结论维度切分，并在 uncertainties 说明。
- **每篇各自成簇**：阈值过严信号；模型应在 themes.md 中做语义归并，把簇数压到 3–8 个主题，并记录归并理由。
- **研究问题超出语料**：综合结论收缩到语料覆盖范围，缺口入 uncertainties。
- **零可用文献**：`status="blocked"`，照常交付说明。

## 7. 默认输出结构（output_contract 缺失时）

```json
{
  "case_id": "…",
  "status": "completed|partial|blocked",
  "research_product": {"question":"…","draft":"review_draft.md 全文","theme_map":"…","bottom_line":"…"},
  "evidence_matrix": [{"claim_id":"C1","doc_id":"D1","anchor":"p3.¶2","statement":"…","direction":"positive","theme":"T1"}],
  "screening_log": {"doc_count":N,"themes":"themes.md 内容","controversy_matrix":"…","gaps":"…"},
  "uncertainties": ["…"],
  "sources": [{"doc_id":"D1","path":"…","sha256":"…","tier":"…","extract_method":"…"}],
  "change_log": ["…"]
}
```

若 case 提供 `output_contract`，逐字段 mirror；缺失内容填 `null` 并在 uncertainties 说明，**不得漏字段**。

## 8. 文件清单

- `scripts/run_case.py`：init / check / finalize 编排。
- `scripts/ingest.py`：防御式解析、材料发现、文本抽取、分级。
- `scripts/extract_claims.py`：候选论断句抽取（结果谓词/数值 + 定位）。
- `scripts/cluster_themes.py`：词项向量连通聚类，主题脚手架。
- `scripts/contradiction_scan.py`：同主题方向相反/数值冲突的论断对扫描。
- `scripts/gap_map.py`：由证据分布推导空白候选。
- `scripts/structure_check.py`：主题覆盖、标记闭合、引用一致性校验。
- `scripts/build_result.py`：result.json 组装与 output_contract 镜像。
- `rules/synthesis_topology.md`、`rules/claim_strength.md`：综合结构与论断强度规则。
- `templates/theme_map.md`、`templates/controversy_matrix.md`：主题图与矛盾矩阵模板。
- `examples/example_walkthrough.md`：示意流程（合成示例）。
