# skill-c-dedup-conflict / dedup-conflict-adjudicator

文献筛选与智能排序挑战赛（challenge-2dd1f64c）的方向 C 作品：一个独立
Skill bundle，用**可审计的规则系统**处理候选文献快照中的重复检测、版本
合并与冲突裁决，并在合并后的 canonical 集合上完成轻量三态筛选。与同题
方向 A（筛选台账）、方向 B（评分排序）完全解耦：独立目录、独立脚本、
无任何引用。

## 是什么

- 三类确定性指纹（规范化标题 / DOI / 首作者姓+年份）对全部候选两两比较，
  每对输出相似度分解与判定档（确证重复簇 / 版本变体 / 疑似重复 / 独立）。
- 簇内按规则 R2 选 canonical；被合并条目以 `merged_into` 保留，绝不静默
  删除；疑似对只进人工复核队列，不自动合并。
- 字段矛盾（年份/期刊/作者/DOI）与夹具标注分歧逐条入冲突台账，带规则
  编号 R1..R6、双方原值、建议裁决或升级；裁决不了的一律升级，不猜。
- 输入夹具的“合成重复导出/冲突意见”标注仅作 provenance 提示，指纹独立
  验证，结论与标注一致/不一致都写明。
- 空候选集、缺元数据（不补造）、无法解析记录、校验失败全部显式入账，
  `status` 始终诚实。

## 目录

```
SKILL.md                      技能说明（frontmatter + 工作流程 + 输出合同）
scripts/normalize.py          防御式归一化 + result.json 骨架
scripts/dedup_engine.py       子命令 fingerprint/conflicts/merge/queue
scripts/assemble.py           校验（V1..V4）+ 组装 result.json 与裁决报告
references/merge_rules.md     规则 R1..R6 全文（指纹档位、canonical 顺序、
                              字段冲突优先级、升级条件、夹具纪律、完整性）
examples/example_walkthrough.md  虚构走查（确证簇 / 疑似对 / 年份冲突升级）
README.md                     本文件
```

## 依赖

Python 3 标准库，无第三方包，无网络。脚本资源总计远小于 2MB。

## 快速验证

```bash
# 最小合成快照（9 条均可，以下 4 条演示三种情形）
T=$(mktemp -d); mkdir -p "$T/app/work" "$T/app/output"
cat > "$T/case.json" <<'EOF'
{"case_id":"demo","research_question":"认知训练是否改善老年工作记忆？",
 "candidates":[
  {"id":"a","title":"Cognitive Training Improves Working Memory in Older Adults",
   "authors":["Ana Silva"],"year":2021,"venue":"arXiv",
   "abstract":"We report a randomized trial of adaptive training in older adults."},
  {"id":"b","title":"Cognitive training improves working memory in older adults",
   "authors":["Silva, Ana"],"year":2022,"venue":"J Cogn Aging",
   "doi":"10.1000/x.1","abstract":"We report a randomized trial of adaptive training in older adults."},
  {"id":"c","title":"A Meta-Analysis of Memory Interventions",
   "authors":["Dana Roth"],"year":2020,"venue":"Meta J","doi":"10.9999/m.5",
   "abstract":"Pooled effects across 41 randomized trials are moderate."},
  {"id":"d","title":"A Meta-Analysis of Memory Interventions",
   "authors":["Dana Roth"],"year":2019,"venue":"Meta J","doi":"10.9999/m.5",
   "abstract":"Pooled effects across 41 randomized trials are moderate."}
 ]}
EOF
S=/path/to/skill-c-dedup-conflict
python3 "$S/scripts/normalize.py" --case "$T/case.json" --work "$T/app/work" --out "$T/app/output"
python3 "$S/scripts/dedup_engine.py" fingerprint --work "$T/app/work"
python3 "$S/scripts/dedup_engine.py" conflicts --work "$T/app/work"
: > "$T/app/work/adjudications.jsonl"   # 空：确认簇自动合并，疑似对留队列
python3 "$S/scripts/dedup_engine.py" merge --work "$T/app/work" \
    --adjudications "$T/app/work/adjudications.jsonl"
python3 "$S/scripts/dedup_engine.py" queue --work "$T/app/work"
# 对 canonical 集合写 screening.jsonl（真实运行由模型完成）后：
python3 "$S/scripts/assemble.py" --work "$T/app/work" --out "$T/app/output"
```

预期：a/b 合并为 version_variant 簇（canonical=b，正式版优先）；c/d 为
确证重复簇且年份矛盾入冲突台账并升级；覆盖率校验通过。

## 限制与维护

- 指纹是词面/元数据级启发式，中文标题退化为字符 bigram；语义近重复
  （换词同义）可能落在疑似带，由模型裁决兜底，这是设计而非缺陷。
- 作者重合度按规范化姓集合计算，同姓异名会产生假信号——因此疑似带
  一律人工裁决，不自动合并。
- 阈值（R1）与优先级（R2/R3）集中在 `dedup_engine.py` 顶部常量与
  `references/merge_rules.md`，调整时两处同步修改。
- 校验失败即非零退出并保留 `status="partial"` 骨架；交付前必须
  `assemble.py` 退出码为 0。
