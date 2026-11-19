# 仅摘要文献政策（abstract_only_policy）

分级为 `abstract_only`（可用正文 <300 词）或仅有题录的文献，处理规则：

1. **不得仅因无全文而排除**。预定义的排除条款只能引用"摘要信息不足以满足 IC#"这一理由，且必须写明缺的是哪一条 IC 所需的哪类信息（如"未报告样本量，无法判定 IC3"）。
2. 纳入的仅摘要文献：在第二轮（fulltext）以摘要代替全文复核，记录的 `reason` 中注明 `abstract_only_review`；其证据行 `strength` 封顶 `suggestive`。
3. 综述正文中引用仅摘要文献时，谓词用"提示/初步表明"，不得用"证实"。
4. 若全部语料均为仅摘要：照常完成两轮筛选与流程记录；综述整体强度封顶 `suggestive`，bottom line 必须明示这一限制。
5. `metadata_only`（连文件都没有的 URL 条目）：不进入筛选统计的判定集，列入 sources 并记 uncertainties，禁止凭标题猜测其内容。
