# literature-review-skills

Three independent, mutually uncoupled Skills for literature-review generation
(Playground challenge `challenge-e97137c9`). Each bundle is self-contained
(own SKILL.md, scripts, rules, templates) and targets a different failure mode
of review-generation agents:

| Bundle | Direction | Core mechanism |
|-|-|-|
| [a-quote-gated-ledger](a-quote-gated-ledger/) | 可核验性 / 正确性 | Every substantive claim must bind a verbatim quote + page/paragraph locator; a script gate verifies quote-at-locator before delivery and demotes anything that fails. |
| [b-prisma-screening](b-prisma-screening/) | 筛选协议 / 可复跑性 | Numbered inclusion/exclusion criteria (IC/EC) written before reading conclusions; per-document decisions citing criteria; dedup groups explicit; PRISMA counts derived by script from the screening log. |
| [c-controversy-cartography](c-controversy-cartography/) | 综合结构 / 分歧保留 | Themes grown from corpus clustering; claims carry direction + anchor; contradiction pairs scanned and adjudicated; research gaps derived from evidence deficits; draft follows claim–evidence–counterevidence–gap structure with a consensus gradient. |

All scripts are Python 3 standard library only; runtime contract is the Harbor
one (`/input/case.json` + `task.md`, work in `/app/work`, deliverables in
`/app/output/result.json` mirroring the case `output_contract`).

Each bundle was smoke-tested locally on synthetic corpora (pass paths,
failure paths, blocked paths). See each bundle's `examples/example_walkthrough.md`.
