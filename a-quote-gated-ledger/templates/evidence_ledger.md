# 证据表模板（evidence_ledger.jsonl，每行一个 JSON 对象）

```json
{"evidence_id":"E1","doc_id":"D1","locator":"p3.¶2","verbatim_quote":"the proposed method reduced error by 3.2% across all four benchmarks","supports":"该方法在四个基准上降低误差 3.2%","theme":"T1 方法性能","strength":"suggestive","notes":"单篇, n=4 基准"}
{"evidence_id":"E2","doc_id":"D2","locator":"p1.¶1","verbatim_quote":"results were not significant for the clinical subgroup","supports":"临床亚组中结果不显著（反面证据）","theme":"T2 临床有效性","strength":"contested","notes":"与 E5 结论相反"}
{"evidence_id":"E9","doc_id":"D4","locator":"p2.¶3","verbatim_quote":"…","supports":"反面证据检索留痕","theme":"T2 临床有效性","strength":"no_adverse_found","notes":"已检索 D1 D2 D5 D7 的局限段, 未见反面证据"}
```

字段与规则见 `rules/citation_binding.md`。写完后运行：

```bash
python3 <scripts>/run_case.py verify --work /app/work --out /app/output
```
