# 表述强度表（草稿谓词与 evidence strength 对应）

草稿中的每个实质论断句必须按其证据 strength 选择谓词；门控脚本只校验标记，但评审会核对谓词与强度是否一致。

| strength | 中文谓词（择一） | 英文对应 | 适用情形 |
|-|-|-|-|
| established | 表明 / 证实 / 已确立 | demonstrates / established | 多篇方法可比文献结论一致，且无未裁决的反证 |
| suggestive | 初步表明 / 提示 | suggests / preliminary evidence | 单篇、仅摘要、作者自述初步、样本有限 |
| contested | 尚有争议 / 结论相反 | conflicting / debated | 语料内存在结论相反的文献且未被判据裁决 |
| unknown | 目前未知 / 尚不清楚 | unclear | 语料未覆盖，明确标 `[证据缺口]` |

## 硬性对应

- `[E#]` 标记的句子，其谓词必须与所挂证据行 strength 匹配：established 行不得写"提示"；suggestive 行不得写"证实"。
- `[推断]` 前缀的句子：由证据可合理推出但未直接陈述的内容；推断链条不得超过一步，且须能在 uncertainties 中说明依据。
- `[证据缺口]`：语料没有证据的论断位置。缺口描述要具体（"缺长期随访数据""两类方法互斥且未在同一基准上比较""研究对象仅限单一人群"），禁止"有待进一步研究"式空话。
- 结论（bottom line）的强度不得超过证据矩阵中最弱的关键环节：任何 bottom line 依赖 suggestive 证据时，须明示。
