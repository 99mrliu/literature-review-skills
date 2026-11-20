# rubric-fusion-ranker

文献筛选与智能排序挑战赛的独立 Skill（方向 B）：**评分卡融合排序 +
逐条理由 + 敏感性稳健性检验**。模型只把研究问题一次性翻译成词表
（criteria_terms.json），六个信号的打分、加权融合、平局协议、top-k
边界扩展、单因子 ±25% 权重敏感性检验全部由确定性脚本完成；每条信号
的打分绑定 title/abstract 原文子串证据，脚本自检防臆造。

## 目录

```
SKILL.md                      技能说明（frontmatter + 八步工作流程 + 自查清单）
scripts/prepare.py            候选集防御式归一化 + 诚实脚手架（stdlib only）
scripts/rank_engine.py        score / sensitivity / assemble 三子命令（stdlib only）
references/rubric.md          rubric.json 语义：信号定义、打分规则、权重理由、
                              证据层级表、阈值、平局协议、敏感性协议
examples/example_walkthrough.md  虚构 3 条记录的完整走查（含真实输出片段）
README.md                     本文件
```

## 依赖

- Python 3（标准库，无第三方包，无网络）。两个脚本均支持 `--help`，
  致命错误非零退出。

## 快速验证

```bash
SKILL_DIR=/path/to/skill-b-rubric-rank
T=$(mktemp -d); mkdir -p "$T/work" "$T/output"
cat > "$T/case.json" <<'EOF'
{"case_id":"smoke","research_question":"Does drug X help adults with disease Y?",
 "records":[{"title":"Drug X for disease Y: a randomized controlled trial",
  "abstract":"Randomized controlled trial of drug X in adults with disease Y.",
  "authors":["A"],"year":2023,"venue":"Trials","doi":"10.1/a"},
  {"title":"Gardening weekly","abstract":"Tomatoes and soil.",
  "authors":["B"],"year":2020,"venue":"Garden"}]}
EOF
python3 "$SKILL_DIR/scripts/prepare.py" --case "$T/case.json" --work "$T/work" --out "$T/output"
cat > "$T/work/criteria_terms.json" <<'EOF'
{"topic_terms":["drug X","disease Y"],"population_terms":["adults"],
 "method_terms":["randomized"],"exclusion_terms":[]}
EOF
python3 "$SKILL_DIR/scripts/rank_engine.py" score --work "$T/work" \
    --terms "$T/work/criteria_terms.json" --rubric "$T/work/rubric.json" \
    --out "$T/work/scored.jsonl"
python3 "$SKILL_DIR/scripts/rank_engine.py" sensitivity --work "$T/work" --k 2
python3 "$SKILL_DIR/scripts/rank_engine.py" assemble --work "$T/work" --out "$T/output" --k 2
# 期望：status=complete，drug-X 文献 rank 1 retained；输出 result.json 与
# ranking_report.md、sensitivity_report.md。
```

异常路径自测（均应优雅处理而非崩溃）：空 `records` →
`status="empty_result"`；`topic_terms` 为空 → score 非零退出；缺
sensitivity.json → assemble 交付 `status="partial"`。

## 限制与维护

- 证据层级靠摘要/标题关键词与 venue 启发判定，描述简略的真实 RCT 可能
  被判 `unknown`（低 S4、confidence=medium）；可在偏好序中调整或扩充
  `LEVEL_PATTERNS`（改后需重跑全链路并更新 references/rubric.md 的
  示例表）。
- 词表匹配是词面匹配：同义词、拼写变体不会自动归一，词表质量（模型
  翻译环节）直接决定 S1–S3 区分度；ASCII 词按词边界匹配，极短缩写
  （如 "AI"）需注意误配。
- 权重与阈值是显式评分卡而非学习所得；改动应记入 change_log 并同步
  references/rubric.md。
- 与方向 A（筛选台账）、方向 C（去重/冲突）完全解耦：独立目录、独立
  脚本、不互相引用；疑似重复记录只经 provenance 与 tie_group 标注，
  去重裁决不属于本技能职责。
