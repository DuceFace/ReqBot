# Retrieval Eval Harness Report (WP-37.1)

## Aggregate
- Queries scored (non-zero ground truth): 35
- Mean precision@5: 0.2571
- Mean recall@5: 0.5599
- Mean recall@10: 0.601
- Mean recall@20: 0.6782
- Mean MRR: 0.678
- Retrieval latency: mean 6506.3ms, p95 7972.8ms
- Zero-truth queries: 8, mean results returned: 20.0
- **2 quer(y/ies) with no scorable ground truth** (non-zero shape, but no known-relevant id — e.g. unextracted content, not a rankable miss): Q-T04, Q-T05

## Per-query

| ID | Shape | Relevant | precision@5 | recall@5 | recall@10 | recall@20 | MRR | Notes |
|---|---|---|---|---|---|---|---|---|
| Q-N01 | narrow | 2 | 0.4 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N02 | narrow | 1 | 0.2 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N03 | narrow | 3 | 0.6 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N04 | narrow | 2 | 0.2 | 0.5 | 0.5 | 0.5 | 1.0 | |
| Q-N05 | narrow | 3 | 0.6 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N06 | narrow | 1 | 0.2 | 1.0 | 1.0 | 1.0 | 0.5 | |
| Q-N07 | narrow | 1 | 0.2 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-B01 | broad | 10 | 0.4 | 0.2 | 0.5 | 0.6 | 1.0 | |
| Q-B02 | broad | 6 | 0.4 | 0.3333 | 0.3333 | 0.5 | 1.0 | |
| Q-B03 | broad | 8 | 0.2 | 0.125 | 0.375 | 0.75 | 1.0 | |
| Q-B04 | broad | 15 | 0.4 | 0.1333 | 0.3333 | 0.5333 | 1.0 | |
| Q-B05 | broad | 29 | 0.6 | 0.1034 | 0.1724 | 0.2759 | 1.0 | |
| Q-Z01 | zero | 0 | — | — | — | — | — | returned 20 result(s) |
| Q-Z02 | zero | 0 | — | — | — | — | — | returned 20 result(s) |
| Q-Z03 | zero | 0 | — | — | — | — | — | returned 20 result(s) |
| Q-Z04 | zero | 0 | — | — | — | — | — | returned 20 result(s) |
| Q-N08 | narrow | 2 | 0.4 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N09 | narrow | 2 | 0.4 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N10 | narrow | 1 | 0.2 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N11 | narrow | 1 | 0.2 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-B06 | broad | 3 | 0.4 | 0.6667 | 0.6667 | 1.0 | 1.0 | |
| Q-B07 | broad | 5 | 0.2 | 0.2 | 0.6 | 0.8 | 0.3333 | |
| Q-B08 | broad | 9 | 0.6 | 0.3333 | 0.5556 | 0.7778 | 0.5 | |
| Q-Z05 | zero | 0 | — | — | — | — | — | returned 20 result(s) |
| Q-Z06 | zero | 0 | — | — | — | — | — | returned 20 result(s) |
| Q-Z07 | zero | 0 | — | — | — | — | — | returned 20 result(s) |
| Q-Z08 | zero | 0 | — | — | — | — | — | returned 20 result(s) |
| Q-C01 | parent_child_context | 4 | 0.0 | 0.0 | 0.0 | 0.5 | 0.0625 | |
| Q-C02 | parent_child_context | 3 | 0.6 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-C03 | parent_child_context | 4 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | |
| Q-C04 | parent_child_context | 3 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | |
| Q-C05 | parent_child_context | 2 | 0.4 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-C06 | parent_child_context | 1 | 0.2 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-C07 | parent_child_context | 2 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | |
| Q-C08 | parent_child_context | 1 | 0.2 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-T01 | table_derived | 2 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | |
| Q-T02 | table_derived | 3 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | |
| Q-T03 | table_derived | 2 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | |
| Q-T04 | table_derived | 0 | — | — | — | — | — | |
| Q-T05 | table_derived | 0 | — | — | — | — | — | |
| Q-O01 | messy_pdf_overgrab | 1 | 0.2 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-O02 | messy_pdf_overgrab | 1 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | |
| Q-O03 | messy_pdf_overgrab | 1 | 0.2 | 1.0 | 1.0 | 1.0 | 0.25 | |
| Q-O04 | messy_pdf_overgrab | 2 | 0.0 | 0.0 | 0.0 | 0.5 | 0.0833 | |
| Q-O05 | messy_pdf_overgrab | 2 | 0.4 | 1.0 | 1.0 | 1.0 | 1.0 | |
