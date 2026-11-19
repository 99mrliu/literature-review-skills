---
name: quote-gated-evidence-ledger
description: 文献综述生成的"逐字引用门控"协议。当任务要求在多篇真实文献（PDF/文本，可含仅摘要、重复、缺元数据文献）上完成筛选、主题归纳、证据组织并写出综述草稿时使用。核心机制：先解析全文并建立页-段锚点，再为每条实质论断建立"逐字摘录+定位"证据行，交付前由脚本自动校验摘录真实出现在所声称位置，校验失败的论断被自动降级或移出终稿，草稿中每个引用标记都能回查到证据表。适用于任何学科的文献综述、系统筛选、趋势分析或选题评估任务；不负责单篇精读、全文翻译与语言润色。
---

# quote-gated-evidence-ledger：逐字引用门控的文献综述生成

## 1. 本 Skill 解决什么问题

文献综述最常见的失败不是写得少，而是**引用与论断脱节**：句子读起来通顺，但所引文献并不支持该句；反面证据与分歧被抹平成一条平滑叙事；结论超出证据范围。本 Skill 把"可回查"作为硬约束：综述的每一句话要么挂在一个**已核验的证据行**上，要么被明确标注为推断或未知。脚本在收尾阶段自动执行**引用门控**（quote gate）：逐字摘录必须在所声称的文档位置真实出现，草稿中的每个证据标记 `[E#]` 必须解析到一条通过校验的证据行，否则该句不得作为事实陈述留在终稿。

三条硬规则（贯穿全程）：

1. **先取证，后写作**：任何进入草稿的实质论断，必须先有证据行 `{evidence_id, doc_id, locator, verbatim_quote, supports, strength}`；取不到证据的论点写入 `uncertainties`，不得凭印象补引。
2. **摘录必须逐字**：`verbatim_quote` 是从解析文本复制的确切子串（允许去掉换行、连字符断词与多余空白），不得转述、不得翻译、不得凭记忆重写。
3. **门控不过即降级**：`scripts/verify_ledger.py` 校验失败的证据行整体移出证据表，草稿中依赖它的句子被改写为推断语气或删除；校验报告必须随交付物一并提交。

## 2. 适用条件与不适用范围

适用：给定一批真实文献与一个具体研究问题，要求完成筛选（纳入/排除）、主题归纳、证据组织并产出综述草稿、趋势分析或选题评估的任务。材料形态可以是电子 PDF、扫描 PDF（尽力解析并在 uncertainties 中说明）、纯文本、仅有摘要的条目。

不适用：单篇论文精读、全文翻译、语言润色、投稿选刊、事实核查式审稿（那是相邻课题）。本 Skill 只负责"从文献集合到带定位引用的综述草稿"这条链。

## 3. 输入契约（运行时防御式解析）

Harbor 运行契约：任务输入在 `/input/case.json` 与 `/input/task.md`；文献材料由 case 指定或位于 `/input/` 下；工作目录 `/app/work`；交付物写入 `/app/output/`。**不得假设字段名**，按以下顺序探测：

1. `case_id`：依次尝试 `case_id`/`id`/`caseId`；取不到时用文件名，并在 uncertainties 注明。
2. 研究问题：递归查找 `research_question`/`question`/`topic`/`title`/`objective`/`rq`；再读 `task.md` 取任务陈述。task.md 的具体要求优先于本文件的通用流程，冲突时以 task.md 为准。
3. 文献清单：递归查找 `documents`/`papers`/`references`/`files`/`literature`/`corpus`/`materials`；元素可以是路径字符串或含 `path`/`file`/`pdf`/`url`/`title` 的字典；都不命中则在 `/input/` 下按 `*.pdf → *.txt → *.md → *.html` 顺序收集。URL 形态的条目若无本地文件，记为 `metadata_only` 并在 uncertainties 说明，不伪造全文内容。
4. `output_contract`：递归查找 `output_contract`/`contract`/`output_fields`/`required_fields`。`build_result.py` 会把这些字段全部 mirror 进 `result.json`；缺省时使用本 Skill 的默认结构（见第 7 节）。

零文献或全部解析失败：仍写出 `status="blocked"` 的 result.json 与说明文档，不得空跑。

## 4. 运行方式（总览）

```bash
S=<skills 目录>/quote-gated-evidence-ledger/scripts
python3 $S/run_case.py init   --case /input/case.json --task /input/task.md --input-dir /input --work /app/work --out /app/output
# ……中间阶段由模型按第 5 节完成（证据表、主题、草稿），全部落盘到 /app/work……
python3 $S/run_case.py verify --work /app/work --out /app/output
python3 $S/run_case.py finalize --case /input/case.json --work /app/work --out /app/output
```

`init` 在 10 秒内产出**第一版 partial result.json**（`status="in_progress"`），此后任何中断都已留有可核对的中间产物。`verify` 执行引用门控并就地修订草稿；`finalize` 组装终版 result.json。

## 5. 工作流程（四阶段，预算内完成）

总预算参考：64 次模型请求、900 秒、单次响应 ≤16384 token（含推理）。**脚本不占模型预算**，重活交给脚本；中间产物每阶段落盘 `/app/work/`。

### 阶段 0：解析与锚点化（脚本，`init`，0 次模型请求）

- `run_case.py init` 完成防御式解析、材料发现、逐文档文本抽取（`pdftotext -layout` → pypdf → 纯文本回退；记录抽取方式与失败原因）、SHA-256 留痕、文档分级（`fulltext` / `abstract_only`：可用正文 <300 词 / `failed`）、近重复检测（标题归一化 + 前缀哈希分组，疑似重复在筛选阶段处理）。
- 产出：`/app/work/docs.jsonl`（每文档一行：doc_id、路径、sha256、字数分级、解析状态）、`pages/<doc_id>.jsonl`（每页一行 `{"page": n, "text": ...}`）、`anchors/<doc_id>.json`（`p<页>.¶<段>` 锚点表）、`extract_meta.json`、`result.partial.json`。
- 自检：文档总数、各分级计数、解析失败清单必须出现在运行日志与 uncertainties 初稿中。

### 阶段 1：筛选与逐文档摘要（模型 1 次/文档或按锚点分批）

先写 `/app/work/screening.md`：纳入/排除标准各 3–6 条，每条给编号（IC1…/EC1…）并绑定研究问题的具体措辞；然后对每篇文档给出 `include/exclude + 理由（引用标准编号）`。仅摘要文献不直接排除：标注 `abstract_only`，只允许其摘要 sentences 进入证据池，且证据行 strength 不得高于 `提示性`。

逐篇阅读（摘要+结论+方法要点，按锚点分块，宁多请求不超 token），为每篇写 `/app/work/digests/<doc_id>.md`，字段：研究对象/数据、方法路线、核心结论（每条带锚点）、报告的关键数字、局限自述。摘要条目只填摘要部分。

### 阶段 2：主题归纳与证据表（模型 3–8 次）

1. 读全部 digest，把主题**从这批文献里长出来**：合并同义方法/对象/结论簇，命名主题与子主题，写 `/app/work/themes.md`（每个主题：边界一句话、支撑文档列表、与该主题无关的文档明确排除）。禁止套"背景/方法/挑战/展望"通用模板——主题必须能指回具体文献簇。
2. 建证据表 `/app/work/evidence_ledger.jsonl`，每行：

```json
{"evidence_id":"E1","doc_id":"D3","locator":"p2.¶4","verbatim_quote":"……","supports":"某方法在X数据集上AUC提升3.2%","theme":"T2","strength":"established|suggestive|contested","quote_lang":"en|zh"}
```

- `strength` 判定依据 `rules/hedging_register.md`：多文档一致且方法可比 → `established`；单文档或仅摘要 → `suggestive`；文献间结论相反 → `contested`（并存列出双方证据行，不得调和）。
- 同一主题内**必须主动寻找反面证据**：至少扫描一遍全部 digest 中该主题的负面/无效结果/局限段落；找不到反面证据时，在证据表记一行 `no_adverse_found` 并注明检索过的文档，而不是默认没有反面证据。

### 阶段 3：草稿生成与引用门控（模型 2–4 次 + 脚本）

按 `/app/work/themes.md` 与证据表写 `/app/output/review_draft.md`（结构与写法见 `templates/review_draft.md` 与 `rules/citation_binding.md`）：中文、书面语、无第一人称；每个实质句尾标证据标记 `[E#]`（多个证据用 `[E3;E7]`）；推断句用 `[推断]` 前缀；证据未覆盖处写 `[证据缺口]` 并落到具体缺口（缺人群、缺长期随访、方法互斥未裁决等），不用套话收尾。

随后：

```bash
python3 $S/run_case.py verify --work /app/work --out /app/output
python3 $S/run_case.py finalize --case /input/case.json --work /app/work --out /app/output
```

- `verify` 逐行做 quote-at-locator 校验（归一化空白与断词后必须是该页文本的子串）、`[E#]` 解析校验、证据表-草稿一致性校验；输出 `/app/output/gate_report.json` 并就地修订草稿（失败句降级为推断或删除）。
- 门控失败后修复一次的流程：回到原文位置重取摘录 → 重跑 `verify`。两轮仍失败则该行进 `uncertainties`，终稿不再引用。
- `finalize` 组装 `result.json`：mirror case 的 `output_contract` 全部字段 + `case_id` + `status` + `sources`（文档清单与 SHA-256）+ `uncertainties` + `change_log`。`status ∈ {completed, partial, blocked}`：`completed` 要求草稿通过门控且覆盖全部纳入主题；`partial` 用于部分文献解析失败或证据不足但已交付可核对产物；`blocked` 用于零可用文献。

## 6. 异常处置（必须识别并写进 uncertainties）

- **仅有摘要**：降级使用，strength ≤ `suggestive`，在草稿与证据表标注 `abstract_only`。
- **元数据不全**（无作者/年份/DOI）：以文件名或 case 提供信息标识，不猜测补齐；在 sources 中标记 `metadata_incomplete`。
- **重复文献**：近重复组在筛选阶段只纳入代表篇，其余记 `duplicate_of`；同一研究的会议版+期刊版算一篇，取信息全者。
- **结论冲突**：并列为 `contested` 证据行，说明各自的对象与条件差异；**不得取平均、不得调和**。
- **语料为空 / 全部解析失败**：`status="blocked"`，result.json 与说明照常交付。
- **研究问题超出语料**：结论范围收缩到语料实际覆盖的问题，缺口写入 uncertainties，不扩写。

## 7. 默认输出结构（output_contract 缺失时）

```json
{
  "case_id": "…",
  "status": "completed|partial|blocked",
  "research_product": {"question": "…", "screening_summary": "…", "themes": ["…"], "draft": "review_draft.md 全文或路径", "bottom_line": "与研究问题直接相关的收敛结论"},
  "evidence_matrix": [{"evidence_id":"E1","doc_id":"D1","locator":"p3.¶2","verbatim_quote":"…","supports":"…","theme":"…","strength":"…","verified":true}],
  "screening_log": {"criteria": {"include": ["IC1 …"], "exclude": ["EC1 …"]}, "decisions": [{"doc_id":"D1","decision":"include","reason":"IC2, IC4"}]},
  "uncertainties": ["…"],
  "sources": [{"doc_id":"D1","path":"…","sha256":"…","tier":"fulltext|abstract_only|failed","metadata":{}}],
  "change_log": ["init: 解析 N 篇…", "verify: M 行通过, K 行降级…"]
}
```

若 case 提供 `output_contract`（字段名列表或字段说明字典），以其为准：逐字段填充上述对应内容，缺失内容填 `null` 并在 uncertainties 说明，**不得漏字段**。

## 8. 文件清单

- `scripts/run_case.py`：阶段 0/verify/finalize 编排器（init 先产 partial result）。
- `scripts/extract_corpus.py`：防御式解析、材料发现、PDF/文本抽取、分级、去重检测、锚点化。
- `scripts/verify_ledger.py`：引用门控（quote-at-locator、标记解析、草稿修订）。
- `scripts/build_result.py`：result.json 组装与 output_contract 镜像。
- `rules/citation_binding.md`：证据行字段规范与绑定规则。
- `rules/hedging_register.md`：表述强度表（established/suggestive/contested/unknown 对应的中文谓词）。
- `templates/evidence_ledger.md`、`templates/review_draft.md`：证据表与草稿模板。
- `examples/example_walkthrough.md`：示意流程（合成示例，非正式案例结果）。
