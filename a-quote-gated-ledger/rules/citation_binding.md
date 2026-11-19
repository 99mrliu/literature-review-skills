# 证据行字段规范与绑定规则

## 证据行（evidence_ledger.jsonl，每行一个 JSON）

| 字段 | 必填 | 说明 |
|-|-|-|
| evidence_id | 是 | `E1, E2, …` 连续编号，全局唯一 |
| doc_id | 是 | 对应 docs.jsonl 的 doc_id（如 `D3`） |
| locator | 是 | `p<页码>.¶<段号>`，如 `p2.¶4`；页码为解析页序号 |
| verbatim_quote | 是 | 该页文本的**逐字**子串；可复制后删除换行与连字符断词，不得改写 |
| supports | 是 | 该证据支撑的论断（一句话，与草稿中的表述一致） |
| theme | 是 | themes.md 中的主题编号或名称 |
| strength | 是 | `established` / `suggestive` / `contested` / `unknown`（`no_adverse_found` 仅用于反面证据检索留痕行） |
| notes | 否 | 对象、条件、样本等限定语 |

## 绑定规则

1. 一个论断可被多行证据支撑，多行时用 `[E3;E7]`；一行证据只支撑一个具体论断，不得笼统写"支持该主题"。
2. 数字必须随证据行走：凡草稿中出现具体数值（百分比、样本量、效应量），该句必须挂含该数字的 evidence 行。
3. `contested` 主题至少两行证据，分别代表冲突双方，且 strength 均为 `contested`；草稿中并陈双方，不得写"总体来看"式调和。
4. 证据强度不与个人相信程度挂钩，只按语料判定：多篇可比方法结论一致 → `established`；单篇、仅摘要、样本极小或作者自述为初步结果 → `suggestive`；结论相反 → `contested`；语料无法判断 → `unknown`。
5. 仅摘要文献（tier=`abstract_only`）的证据行 strength 不得高于 `suggestive`，quote 取摘要页的逐字文本。
6. 反面证据检索：每个主题在写草稿前，须把该主题全部 digest 的"局限/无效结果/负面结论"段落过一遍；检索过程在证据表留一行 `{"strength":"no_adverse_found","notes":"已检索 D2 D5 D8, 未见反面证据"}`。
