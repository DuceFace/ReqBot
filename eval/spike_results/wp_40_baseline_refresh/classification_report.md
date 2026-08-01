# WP-40 Failure Classification Report

## Harness aggregate (expanded ~50-query set)
- mean_recall@5: 0.582
- mean_recall@10: 0.6538
- mean_recall@20: 0.7106
- mean_mrr: 0.7238
- non-zero queries scored: 37
- zero-truth queries: 8, mean results returned: 20.0

## Category prevalence

| Category | Count |
|---|---|
| extraction_failure | 9 |
| missing_context | 10 |
| table_serialization | 5 |
| embedding_miss | 8 |
| ranking_miss | 18 |
| over_grab | 19 |
| query_filter_issue | 5 |
| zero_truth_confidence_failure | 0 |

- extraction_failure sub-counts: (a) absent_from_corpus=7, (b) never_extracted=2
- zero-truth queries never reporting empty: True

## Miss classifications (detail)

| query_id | requirement_id | category | evidence |
|---|---|---|---|
| Q-N03 | REQ-19f5e7133b96 | extraction_failure | REQ-19f5e7133b96 not present in any current *_requirements_normalized.jsonl winning-tier file (post-Step-D-reprocess corpus). |
| Q-N04 | REQ-cbc6374a655f | extraction_failure | REQ-cbc6374a655f not present in any current *_requirements_normalized.jsonl winning-tier file (post-Step-D-reprocess corpus). |
| Q-B01 | REQ-6fc878342d73 | ranking_miss | REQ-6fc878342d73: present in the top_k=100/min_score=0 pool at rank 61 (score=0.0511 >= floor) but outside production top-20. |
| Q-B01 | REQ-71da6dfa4ff6 | ranking_miss | REQ-71da6dfa4ff6: present in the top_k=100/min_score=0 pool at rank 65 (score=0.0493 >= floor) but outside production top-20. |
| Q-B01 | REQ-c9fb01a1de64 | ranking_miss | REQ-c9fb01a1de64: present in the top_k=100/min_score=0 pool at rank 37 (score=0.0771 >= floor) but outside production top-20. |
| Q-B01 | REQ-ceca6f11ee37 | query_filter_issue | REQ-ceca6f11ee37 appears in a raw-query (no rewrite/HyDE) top-20 but not production's -- the rewrite/HyDE transformation pushed it out. |
| Q-B01 | REQ-dc24c38b9701 | embedding_miss | REQ-dc24c38b9701 absent even from top_k=100/min_score=0 pool (100 candidates) -- genuine semantic/vocabulary mismatch. |
| Q-B02 | REQ-6b00bb3cc8aa | embedding_miss | REQ-6b00bb3cc8aa absent even from top_k=100/min_score=0 pool (100 candidates) -- genuine semantic/vocabulary mismatch. |
| Q-B02 | REQ-6ede29bd318f | ranking_miss | REQ-6ede29bd318f: present in the top_k=100/min_score=0 pool at rank 37 (score=0.0804 >= floor) but outside production top-20. |
| Q-B02 | REQ-75692d2c3b99 | missing_context | REQ-75692d2c3b99: fragment-shaped (_is_reconstruction_candidate=True) but parent_stem is empty -- source_quote='If remote administration is enabled in a hypervisor, access to all remote administration interfaces ' |
| Q-B03 | REQ-0a7205b45a34 | ranking_miss | REQ-0a7205b45a34: present in the top_k=100/min_score=0 pool at rank 36 (score=0.0722 >= floor) but outside production top-20. |
| Q-B04 | REQ-32fd3744782c | embedding_miss | REQ-32fd3744782c absent even from top_k=100/min_score=0 pool (100 candidates) -- genuine semantic/vocabulary mismatch. |
| Q-B04 | REQ-34637afacfba | ranking_miss | REQ-34637afacfba: present in the top_k=100/min_score=0 pool at rank 35 (score=0.0976 >= floor) but outside production top-20. |
| Q-B04 | REQ-8313e79684fd | ranking_miss | REQ-8313e79684fd: present in the top_k=100/min_score=0 pool at rank 20 (score=0.1672 >= floor) but outside production top-20. |
| Q-B04 | REQ-c3615152818c | missing_context | REQ-c3615152818c: fragment-shaped (_is_reconstruction_candidate=True) but parent_stem is empty -- source_quote='Submit a final IR within 24 hours of the all action related to the incident being completed.' |
| Q-B04 | REQ-e89da233db7e | missing_context | REQ-e89da233db7e: fragment-shaped (_is_reconstruction_candidate=True) but parent_stem is empty -- source_quote='Personnel should continuously review, corroborate, and update (if applicable) the reported incident ' |
| Q-B04 | REQ-ec4f782c42cc | ranking_miss | REQ-ec4f782c42cc: present in the top_k=100/min_score=0 pool at rank 34 (score=0.0995 >= floor) but outside production top-20. |
| Q-B05 | REQ-040038ca5a22 | ranking_miss | REQ-040038ca5a22: present in the top_k=100/min_score=0 pool at rank 42 (score=0.0666 >= floor) but outside production top-20. |
| Q-B05 | REQ-062332da9327 | ranking_miss | REQ-062332da9327: present in the top_k=100/min_score=0 pool at rank 82 (score=0.0336 >= floor) but outside production top-20. |
| Q-B05 | REQ-10219b48059c | embedding_miss | REQ-10219b48059c absent even from top_k=100/min_score=0 pool (100 candidates) -- genuine semantic/vocabulary mismatch. |
| Q-B05 | REQ-24f365872807 | query_filter_issue | REQ-24f365872807 appears in a raw-query (no rewrite/HyDE) top-20 but not production's -- the rewrite/HyDE transformation pushed it out. |
| Q-B05 | REQ-3a28755e1e4e | ranking_miss | REQ-3a28755e1e4e: present in the top_k=100/min_score=0 pool at rank 33 (score=0.0855 >= floor) but outside production top-20. |
| Q-B05 | REQ-3ba1011588d0 | embedding_miss | REQ-3ba1011588d0 absent even from top_k=100/min_score=0 pool (100 candidates) -- genuine semantic/vocabulary mismatch. |
| Q-B05 | REQ-3d5d46029848 | embedding_miss | REQ-3d5d46029848 absent even from top_k=100/min_score=0 pool (100 candidates) -- genuine semantic/vocabulary mismatch. |
| Q-B05 | REQ-44d9dec82620 | ranking_miss | REQ-44d9dec82620: present in the top_k=100/min_score=0 pool at rank 62 (score=0.0426 >= floor) but outside production top-20. |
| Q-B05 | REQ-611bb564a245 | ranking_miss | REQ-611bb564a245: present in the top_k=100/min_score=0 pool at rank 84 (score=0.0335 >= floor) but outside production top-20. |
| Q-B05 | REQ-6c41a63b4601 | ranking_miss | REQ-6c41a63b4601: present in the top_k=100/min_score=0 pool at rank 66 (score=0.0391 >= floor) but outside production top-20. |
| Q-B05 | REQ-9c7e09003f88 | embedding_miss | REQ-9c7e09003f88 absent even from top_k=100/min_score=0 pool (100 candidates) -- genuine semantic/vocabulary mismatch. |
| Q-B05 | REQ-9d61639d1f89 | missing_context | REQ-9d61639d1f89: fragment-shaped (_is_reconstruction_candidate=True) but parent_stem is empty -- source_quote='The CARM Program utilizes products from three separate assessments to determine risk to AF TCAs and ' |
| Q-B05 | REQ-b307f533b9fa | missing_context | REQ-b307f533b9fa: fragment-shaped (_is_reconstruction_candidate=True) but parent_stem is empty -- source_quote='(2) Assess risk, and plan and implement mitigations to ensure the confidentiality, integrity, availa' |
| Q-B05 | REQ-d45401b1a7b1 | missing_context | REQ-d45401b1a7b1: fragment-shaped (_is_reconstruction_candidate=True) but parent_stem is empty -- source_quote='Establish and maintain an operational TSN program to enable risk owners to identify, assess, and man' |
| Q-B05 | REQ-e9e83b3ec2e5 | ranking_miss | REQ-e9e83b3ec2e5: present in the top_k=100/min_score=0 pool at rank 73 (score=0.0376 >= floor) but outside production top-20. |
| Q-B05 | REQ-edc0df1cb13c | embedding_miss | REQ-edc0df1cb13c absent even from top_k=100/min_score=0 pool (100 candidates) -- genuine semantic/vocabulary mismatch. |
| Q-B05 | REQ-ee004d53c363 | query_filter_issue | REQ-ee004d53c363 appears in a raw-query (no rewrite/HyDE) top-20 but not production's -- the rewrite/HyDE transformation pushed it out. |
| Q-B05 | REQ-f4ad3db3e934 | ranking_miss | REQ-f4ad3db3e934: present in the top_k=100/min_score=0 pool at rank 47 (score=0.0581 >= floor) but outside production top-20. |
| Q-B05 | REQ-f78038d96493 | ranking_miss | REQ-f78038d96493: present in the top_k=100/min_score=0 pool at rank 63 (score=0.0411 >= floor) but outside production top-20. |
| Q-B07 | REQ-8e758ed53c4a | missing_context | REQ-8e758ed53c4a: fragment-shaped (_is_reconstruction_candidate=True) but parent_stem is empty -- source_quote='Establish and maintain configuration management of AN/USQ-225 operational, implementation, and targe' |
| Q-C03 | REQ-0c36ee7705d6 | ranking_miss | REQ-0c36ee7705d6: present in the top_k=100/min_score=0 pool at rank 84 (score=0.0358 >= floor) but outside production top-20. |
| Q-C03 | REQ-1cc75ab1ae84 | missing_context | REQ-1cc75ab1ae84: fragment-shaped (_is_reconstruction_candidate=True) but parent_stem is empty -- source_quote='There are no contract restrictions prohibiting access to such information.' |
| Q-C03 | REQ-8b4912b3e342 | missing_context | REQ-8b4912b3e342: fragment-shaped (_is_reconstruction_candidate=True) but parent_stem is empty -- source_quote='Access to such information is in accordance with DoDIs 8500.01 and 5200.02 and export control regula' |
| Q-C03 | REQ-e82948a97dc5 | missing_context | REQ-e82948a97dc5: fragment-shaped (_is_reconstruction_candidate=True) but parent_stem is empty -- source_quote='Access to such information is within the scope of their assigned duties.' |
| Q-C04 | REQ-4523443092b8 | extraction_failure | REQ-4523443092b8 not present in any current *_requirements_normalized.jsonl winning-tier file (post-Step-D-reprocess corpus). |
| Q-C04 | REQ-cbc6374a655f | extraction_failure | REQ-cbc6374a655f not present in any current *_requirements_normalized.jsonl winning-tier file (post-Step-D-reprocess corpus). |
| Q-C04 | REQ-e0471aa64a63 | extraction_failure | REQ-e0471aa64a63 not present in any current *_requirements_normalized.jsonl winning-tier file (post-Step-D-reprocess corpus). |
| Q-C05 | REQ-97e6e5483093 | extraction_failure | REQ-97e6e5483093 not present in any current *_requirements_normalized.jsonl winning-tier file (post-Step-D-reprocess corpus). |
| Q-C06 | REQ-1b1071c8d317 | extraction_failure | REQ-1b1071c8d317 not present in any current *_requirements_normalized.jsonl winning-tier file (post-Step-D-reprocess corpus). |
| Q-C07 | REQ-6b00bb3cc8aa | query_filter_issue | REQ-6b00bb3cc8aa appears in a raw-query (no rewrite/HyDE) top-20 but not production's -- the rewrite/HyDE transformation pushed it out. |
| Q-C07 | REQ-cf527f39c8d7 | query_filter_issue | REQ-cf527f39c8d7 appears in a raw-query (no rewrite/HyDE) top-20 but not production's -- the rewrite/HyDE transformation pushed it out. |
| Q-T01 | REQ-5c349cdc3656 | table_serialization | REQ-5c349cdc3656 (chunk_id=55, doc=afi17-203): source_quote or its chunk's raw_text matches the GARBLED_TABLE 'Column = Value' run-on signature. |
| Q-T01 | REQ-68e7c7d2ba86 | table_serialization | REQ-68e7c7d2ba86 (chunk_id=55, doc=afi17-203): source_quote or its chunk's raw_text matches the GARBLED_TABLE 'Column = Value' run-on signature. |
| Q-T02 | REQ-294c93fbd5f5 | table_serialization | REQ-294c93fbd5f5 (chunk_id=111, doc=afi10-2402): source_quote or its chunk's raw_text matches the GARBLED_TABLE 'Column = Value' run-on signature. |
| Q-T02 | REQ-8a9662ea5d56 | table_serialization | REQ-8a9662ea5d56 (chunk_id=111, doc=afi10-2402): source_quote or its chunk's raw_text matches the GARBLED_TABLE 'Column = Value' run-on signature. |
| Q-T02 | REQ-d724d2b52a9b | table_serialization | REQ-d724d2b52a9b (chunk_id=111, doc=afi10-2402): source_quote or its chunk's raw_text matches the GARBLED_TABLE 'Column = Value' run-on signature. |
| Q-T04 | None | extraction_failure | DODI 5200.48 chunk_id=58, Table 1 (DoD CUI Registry Category Examples): raw chunk text reads "NNPI, Proposed Defense Description = Related to the safety of reactors and associated naval nuclear propulsion plants, and control of radiation and radioactivity..." -- GARBLED_TABLE signature confirmed (is_garbled_table_text), zero Step D records survive for this chunk (whole table content lost, not just decontextualized). |
| Q-T05 | None | extraction_failure | DODI 8551.01 chunk_id=26, G.1 Acronyms table: raw chunk text reads "CAL, MEANING = category assurance list. CCB, MEANING = configuration control board." -- GARBLED_TABLE signature confirmed (is_garbled_table_text), zero Step D records survive for this chunk. |

## Over-grab findings

| query_id | requirement_id | rank | evidence |
|---|---|---|---|
| Q-N01 | REQ-cdac2ad9724b | 3 | REQ-cdac2ad9724b shares chunk ('dafman17-1305', 105) with a relevant record for query Q-N01 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-N06 | REQ-dbaf782e8042 | 2 | REQ-dbaf782e8042 shares chunk ('DODI 8410.03', 29) with a relevant record for query Q-N06 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-N06 | REQ-354c9774c06d | 3 | REQ-354c9774c06d shares chunk ('DODI 8410.03', 29) with a relevant record for query Q-N06 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-N06 | REQ-b892fd30193d | 4 | REQ-b892fd30193d shares chunk ('DODI 8410.03', 29) with a relevant record for query Q-N06 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-N06 | REQ-b73da299e723 | 5 | REQ-b73da299e723 shares chunk ('DODI 8410.03', 29) with a relevant record for query Q-N06 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-N07 | REQ-dbaf782e8042 | 2 | REQ-dbaf782e8042 shares chunk ('DODI 8410.03', 29) with a relevant record for query Q-N07 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-N07 | REQ-b73da299e723 | 4 | REQ-b73da299e723 shares chunk ('DODI 8410.03', 29) with a relevant record for query Q-N07 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-N07 | REQ-b892fd30193d | 5 | REQ-b892fd30193d shares chunk ('DODI 8410.03', 29) with a relevant record for query Q-N07 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-B04 | REQ-775b96d1622a | 3 | REQ-775b96d1622a shares chunk ('afi17-203', 23) with a relevant record for query Q-B04 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-B05 | REQ-9ece516563ab | 3 | REQ-9ece516563ab shares chunk ('DODI 5200.44', 6) with a relevant record for query Q-B05 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-N08 | REQ-f50c31b9e834 | 4 | REQ-f50c31b9e834 shares chunk ('DODI 5200.01', 5) with a relevant record for query Q-N08 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-C03 | REQ-b688ddb1fe9c | 2 | REQ-b688ddb1fe9c shares chunk ('DODI 5200.48', 64) with a relevant record for query Q-C03 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-O01 | REQ-189d6285eaa2 | 4 | REQ-189d6285eaa2 hand-labeled as a known over-broad/duplicate extraction for query Q-O01. |
| Q-O02 | REQ-cc458f334808 | 1 | REQ-cc458f334808 hand-labeled as a known over-broad/duplicate extraction for query Q-O02. |
| Q-O02 | REQ-eeb283685157 | 3 | REQ-eeb283685157 shares chunk ('afi17-203', 57) with a relevant record for query Q-O02 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-O04 | REQ-ee58af92484e | 2 | REQ-ee58af92484e shares chunk ('afi10-2402', 87) with a relevant record for query Q-O04 -- likely duplicate/near-duplicate fragment of the same source clause. |
| Q-O04 | REQ-9de207b16791 | 3 | REQ-9de207b16791 hand-labeled as a known over-broad/duplicate extraction for query Q-O04. |
| Q-O05 | REQ-ed8684f5020a | 3 | REQ-ed8684f5020a hand-labeled as a known over-broad/duplicate extraction for query Q-O05. |
| Q-O05 | REQ-9f12eac0a73a | 5 | REQ-9f12eac0a73a shares chunk ('DODI 5200.48', 66) with a relevant record for query Q-O05 -- likely duplicate/near-duplicate fragment of the same source clause. |

