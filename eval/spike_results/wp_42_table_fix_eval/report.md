# Retrieval Eval Harness Report (WP-37.1)

## Aggregate
- Queries scored (non-zero ground truth): 37
- Mean recall@5: 0.6737
- Mean recall@10: 0.7255
- Mean recall@20: 0.7658
- Mean MRR: 0.75
- Zero-truth queries: 8, mean results returned: 20.0

## Per-query

| ID | Shape | Relevant | recall@5 | recall@10 | recall@20 | MRR | Notes |
|---|---|---|---|---|---|---|---|
| Q-N01 | narrow | 2 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N02 | narrow | 1 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N03 | narrow | 3 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N04 | narrow | 2 | 0.5 | 0.5 | 0.5 | 1.0 | |
| Q-N05 | narrow | 3 | 0.6667 | 1.0 | 1.0 | 0.5 | |
| Q-N06 | narrow | 1 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N07 | narrow | 1 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-B01 | broad | 10 | 0.2 | 0.3 | 0.4 | 0.5 | |
| Q-B02 | broad | 6 | 0.1667 | 0.3333 | 0.3333 | 0.3333 | |
| Q-B03 | broad | 8 | 0.25 | 0.5 | 0.625 | 0.3333 | |
| Q-B04 | broad | 15 | 0.2667 | 0.2667 | 0.4667 | 1.0 | |
| Q-B05 | broad | 29 | 0.1379 | 0.2759 | 0.3448 | 1.0 | |
| Q-Z01 | zero | 0 | — | — | — | — | returned 20 result(s) |
| Q-Z02 | zero | 0 | — | — | — | — | returned 20 result(s) |
| Q-Z03 | zero | 0 | — | — | — | — | returned 20 result(s) |
| Q-Z04 | zero | 0 | — | — | — | — | returned 20 result(s) |
| Q-N08 | narrow | 2 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N09 | narrow | 2 | 0.5 | 1.0 | 1.0 | 1.0 | |
| Q-N10 | narrow | 1 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N11 | narrow | 1 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-B06 | broad | 3 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-B07 | broad | 5 | 0.6 | 0.6 | 0.6 | 1.0 | |
| Q-B08 | broad | 9 | 0.4444 | 0.6667 | 1.0 | 1.0 | |
| Q-Z05 | zero | 0 | — | — | — | — | returned 20 result(s) |
| Q-Z06 | zero | 0 | — | — | — | — | returned 20 result(s) |
| Q-Z07 | zero | 0 | — | — | — | — | returned 20 result(s) |
| Q-Z08 | zero | 0 | — | — | — | — | returned 20 result(s) |
| Q-C01 | parent_child_context | 4 | 0.5 | 0.5 | 1.0 | 0.3333 | |
| Q-C02 | parent_child_context | 3 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-C03 | parent_child_context | 4 | 0.0 | 0.0 | 0.0 | 0.0 | |
| Q-C04 | parent_child_context | 3 | 0.0 | 0.0 | 0.0 | 0.0 | |
| Q-C05 | parent_child_context | 2 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-C06 | parent_child_context | 1 | 1.0 | 1.0 | 1.0 | 0.25 | |
| Q-C07 | parent_child_context | 2 | 0.0 | 0.0 | 0.0 | 0.0 | |
| Q-C08 | parent_child_context | 1 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-T01 | table_derived | 0 | — | — | — | — | |
| Q-T02 | table_derived | 3 | 0.0 | 0.0 | 0.0 | 0.0 | |
| Q-T03 | table_derived | 0 | — | — | — | — | |
| Q-T04 | table_derived | 0 | — | — | — | — | |
| Q-T05 | table_derived | 0 | — | — | — | — | |
| Q-O01 | messy_pdf_overgrab | 1 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-O02 | messy_pdf_overgrab | 1 | 1.0 | 1.0 | 1.0 | 0.5 | |
| Q-O03 | messy_pdf_overgrab | 1 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-O04 | messy_pdf_overgrab | 2 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-O05 | messy_pdf_overgrab | 2 | 1.0 | 1.0 | 1.0 | 1.0 | |
