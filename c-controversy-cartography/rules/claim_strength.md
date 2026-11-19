# 论断强度规则（claim_strength）

## direction 裁定（claims.jsonl）

| direction | 含义 | 典型措辞 |
|-|-|-|
| positive | 支持研究问题中的效果/优势主张 | improves, outperforms, 提升, 优于, 显著 |
| negative | 反面证据：无效、更差、不显著、局限 | no effect, did not, failed, 无效, 未发现, 局限 |
| neutral | 背景、方法描述、与效果无关的陈述 | — |

- 作者自述的 limitation 一律 `negative`，即使正文结论为 positive：它是该文献证据强度的自证上限。
- 无法判定的候选句不进入 claims.jsonl，留在 claims_candidates.jsonl 即可。

## 谓词-梯度对应（草稿）

- `已确立` → "表明/证实"；`有提示` → "初步表明/提示"；`有争议` → "尚有争议/结论相反"。
- 单源主题的实质句谓词不得强于"初步表明"。
- 数值精度不得超过原文：原文"约 4%"不得写成"4.0%"。

## 冲突裁决（controversy_matrix.md）

- `explained`：双方对象/条件/指标/剂量可解释差异，写明解释；该对不再标争议，但双方论断仍各自保留在草稿中。
- `unresolved_conflict`：无可信解释；草稿并陈，主题梯度降一档至"有争议"。
- 裁决理由必须引用双方的 `[C#]` 论断内容，不得空判。
