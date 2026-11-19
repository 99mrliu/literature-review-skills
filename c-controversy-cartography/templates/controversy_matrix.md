# 矛盾矩阵模板（controversy_matrix.md）

`contradiction_scan.py` 先产出候选对 `controversy_candidates.json`；模型逐对裁决：

```markdown
# 矛盾矩阵

## X1 (T2, opposite_direction)
- C2 (D1): "域内 F1 提升 4.1 点"
- C5 (D4): "未见显著改善"
- 裁决：unresolved_conflict
- 理由：两者同为 Y 任务且对象一致，指标均为 F1，但样本与协议不同，语料内无 head-to-head 比较可解释差异。
- 对空白的影响：触发 G2（缺直接比较）

## X2 (T3, metric_conflict)
- C8 (D2): "误差 −3.2%"
- C9 (D6): "误差 +1.0%"
- 裁决：explained
- 理由：C8 为域内测试，C9 为跨域测试；条件差异足以解释方向相反，不构成争议。
```

规则：裁决只能为 `explained` 或 `unresolved_conflict`；理由必须引用双方论断原文；`unresolved_conflict` 触发 gap_map 的 `unresolved_conflict` 空白候选。
