# PRISMA 流程模板（数字由 prisma_flow.py 生成，禁止手写替换）

finalize 阶段自动生成 `prisma_flow.md` / `prisma_flow.json`，结构：

```
# PRISMA 流程记录（由 prisma_flow.py 从筛选日志推导）

- 识别文献: N
- 去重后保留: N
- 题录/摘要筛序: N（排除 N）
- 全文复核: N（排除 N）
- 最终纳入: N

## 排除理由分布（标准编号 → 篇数）
- EC1: n
- EC2: n
```

人读版综述的"研究问题与语料"一节应引用此流程；result.json 的 `screening_log.prisma_flow` 字段携带机读版。若审计发现日志计数与流程不一致，以日志为准并修复流程（流程永远是日志的函数）。
