# prisma-screen-ledger

文献筛选与智能排序——**协议化双门三态筛选与判定台账**方向的作品。

## 是什么

给定研究问题与有限候选文献快照，对全部条目完成逐条相关性判断、
三态标签（retained / pending / excluded）与确定性排序，交付
`result.json` + 人工可复核的 `screening_report.md`。与“评分排序”
方向不同，本作品把质量押在**协议与会计校验**上：每条裁决绑定标准
编号、原文引用、置信度；脚本校验覆盖率 100%、引用确为原文子串、
三层台账对账，校验不过不交付。

## 目录

```
SKILL.md                 主指令（工作流八步、排序约定、异常处理）
README.md                本说明
scripts/prepare.py       case.json → records.jsonl / case_meta.json / result 骨架
scripts/ledger.py        check（台账会计校验） / assemble（结果与报告）
references/label_system.md   标签体系、标准模板、边界案例约定
examples/example_walkthrough.md  虚构走查（接口示意）
```

## 依赖与安装

- Python 3.8+，**仅标准库**，无需网络与第三方包。
- 运行时 Skill 安装于 `/skills/weekly-skill`；脚本内有失效时的
  自动定位回退（见 SKILL.md“运行环境”）。

## 快速验证

```bash
python3 scripts/ledger.py --help
python3 scripts/prepare.py --help
```

对任一含候选记录的 case.json 走完 SKILL.md 八步即可复现交付物；
复核人可拿输出目录中的 `criteria.json` + `decisions.jsonl` 重跑
`ledger.py check` 独立验证。

## 限制与维护

- 判断证据限于快照内题录/摘要，不做联网召回，不读快照外全文；
- 不做学习式打分与语义相似度，排序完全确定性；
- 疑似重复不删除不合并（完整性优先），仅打标记供人工裁决；
- 维护：标准模板与边界案例随学科反馈更新于 references/ 下，版本
  变更记入 result.json 的 change_log 字段。
