# Retrieval Eval Harness Report (WP-37.1)

## Aggregate
- Queries scored (non-zero ground truth): 12
- Mean recall@5: 0.5767
- Mean recall@10: 0.663
- Mean recall@20: 0.7363
- Mean MRR: 0.9028
- Zero-truth queries: 4, mean results returned: 20.0

## Per-query

| ID | Shape | Relevant | recall@5 | recall@10 | recall@20 | MRR | Notes |
|---|---|---|---|---|---|---|---|
| Q-N01 | narrow | 2 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N02 | narrow | 1 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N03 | narrow | 4 | 0.5 | 0.75 | 0.75 | 1.0 | |
| Q-N04 | narrow | 2 | 0.5 | 0.5 | 0.5 | 1.0 | |
| Q-N05 | narrow | 3 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N06 | narrow | 1 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-N07 | narrow | 1 | 1.0 | 1.0 | 1.0 | 1.0 | |
| Q-B01 | broad | 10 | 0.2 | 0.3 | 0.3 | 1.0 | |
| Q-B02 | broad | 6 | 0.1667 | 0.3333 | 0.5 | 0.3333 | |
| Q-B03 | broad | 8 | 0.25 | 0.5 | 0.875 | 0.5 | |
| Q-B04 | broad | 15 | 0.2 | 0.4 | 0.6 | 1.0 | |
| Q-B05 | broad | 29 | 0.1034 | 0.1724 | 0.3103 | 1.0 | |
| Q-Z01 | zero | 0 | — | — | — | — | returned 20 result(s) |
| Q-Z02 | zero | 0 | — | — | — | — | returned 20 result(s) |
| Q-Z03 | zero | 0 | — | — | — | — | returned 20 result(s) |
| Q-Z04 | zero | 0 | — | — | — | — | returned 20 result(s) |
