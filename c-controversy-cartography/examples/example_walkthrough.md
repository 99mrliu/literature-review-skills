# 示意流程（合成示例，仅说明接口，非任何正式案例的结果）

语料：D1 域内性能研究、D2 域内+跨域研究、D3 综述（非原始研究，仍参与主题归属与覆盖判断但不产论断）。

1. `run_case.py init` → docs.jsonl、claims_candidates.jsonl（含结果谓词/数值句）、theme_scaffold.json（T1={D1,D2} 性能主题、T2={D3} 背景主题）。
2. 模型写 claims.jsonl：C1(D1, positive, "域内 F1 +4.1")、C2(D2, positive, "域内 +2.0")、C3(D2, negative, "跨域不显著")、C4(D1, negative, "局限: 单域")。写 themes.md 与 themes_map.json。
3. `run_case.py check` 先跑 contradiction_scan：C1 vs C3 方向不同但主题不同（若都归 T1 则成 X1 候选）；gap_map：T? 单源 → G 候选。
4. 模型写 controversy_matrix.md（X1 裁决 explained：域内 vs 跨域条件不同）、gaps.md（"跨域证据仅 D2 一篇，无第三方复现"）。
5. 模型写 review_draft.md：T1 节四拍成文，挂 [C1;C2]、[C3] [X1]、[G#]，末尾共识梯度"有提示"。
6. `check` 通过 → `finalize` → result.json status=completed。

以上文献与数字均为演示虚构。
