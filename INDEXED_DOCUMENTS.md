# Indexed Documents

Documents currently in the Qdrant `grc_requirements` collection.
Run `python3 grcai.py docs` to see a live view with up-to-date counts.

Last updated: 2026-03-08 | Total: 45 documents, 28,826 requirements

> **Extraction mode note:** `pdfplumber` is detected from the presence of table
> sentinels in the chunk file. DODI docs re-run on 2026-03-07 were all processed
> with `--layout-mode pdfplumber`, but those without structured tables will show
> as `pymupdf` in the detection heuristic.

---

## CJCSI / CNSSI

| Document | Requirements | Extraction | Last Run |
|----------|-------------|------------|----------|
| CJCSI 6510.02G | 93 | pymupdf | 2026-03-06 |
| CJCSI6510_01F | 867 | pymupdf | 2026-03-06 |
| CNSSI_No1253 | 1,368 | pymupdf | 2026-03-06 |

## DoD Instructions / Manuals

| Document | Requirements | Extraction | Last Run |
|----------|-------------|------------|----------|
| DODI 5200.01 | 84 | pdfplumber | 2026-03-07 |
| DODI 5200.01_vol1 | 531 | pdfplumber | 2026-03-07 |
| DODI 5200.01_vol2 | 564 | pdfplumber | 2026-03-07 |
| DODI 5200.01_vol3 | 965 | pdfplumber | 2026-03-07 |
| DODI 5200.44 | 125 | pdfplumber | 2026-03-07 |
| DODI 5200.48 | 234 | pdfplumber | 2026-03-07 |
| DODI 8410.03 | 151 | pdfplumber | 2026-03-07 |
| DODI 8500.01 | 394 | pdfplumber | 2026-03-07 |
| DODI 8510.01 | 247 | pdfplumber | 2026-03-07 |
| DODI 8520.02 | 304 | pdfplumber | 2026-03-07 |
| DODI 8530.01 | 299 | pymupdf | 2026-03-06 |
| DODI 8551.01 | 76 | pdfplumber | 2026-03-07 |
| DODM 8140.03 | 172 | pdfplumber | 2026-03-07 |

## NIST Special Publications

| Document | Requirements | Extraction | Last Run |
|----------|-------------|------------|----------|
| NIST.SP.800-30r1 | 671 | pymupdf | 2026-03-06 |
| NIST.SP.800-37r2 | 1,034 | pymupdf | 2026-03-06 |
| NIST.SP.800-53r5 | 3,520 | pymupdf | 2026-03-06 |
| NIST.SP.800-53Ar5 | 5,486 | pymupdf | 2026-03-06 |
| NIST.SP.800-61r3 | 246 | pymupdf | 2026-03-06 |
| NIST.SP.800-63-4 | 375 | pymupdf | 2026-03-06 |
| NIST.SP.800-63a-4 | 660 | pymupdf | 2026-03-06 |
| NIST.SP.800-63b-4 | 779 | pymupdf | 2026-03-06 |
| NIST.SP.800-63c-4 | 832 | pymupdf | 2026-03-06 |
| NIST.SP.800-92 | 411 | pymupdf | 2026-03-06 |
| NIST.SP.800-125 | 219 | pymupdf | 2026-03-05 |
| NIST.SP.800-128 | 542 | pymupdf | 2026-03-06 |
| NIST.SP.800-137 | 467 | pymupdf | 2026-03-06 |
| NIST.SP.800-161r1 | 2,201 | pymupdf | 2026-03-06 |
| NIST.SP.800-171r3 | 816 | pymupdf | 2026-03-06 |

## Air Force Instructions / Publications

| Document | Requirements | Extraction | Last Run |
|----------|-------------|------------|----------|
| afpd_17-1 | 137 | pymupdf | 2026-03-06 |
| afi10-2402 | 373 | pymupdf | 2026-03-06 |
| afi13-550 | 203 | pymupdf | 2026-03-06 |
| afi17-101 | 307 | pymupdf | 2026-03-06 |
| afi17-130 | 136 | pymupdf | 2026-03-06 |
| afi17-203 | 145 | pymupdf | 2026-03-06 |
| afi90-802 | 210 | pymupdf | 2026-03-06 |
| afman17-204 | 117 | pymupdf | 2026-03-06 |
| afman17-2101 | 178 | pymupdf | 2026-03-06 |

## DAF Manuals / Pamphlets

| Document | Requirements | Extraction | Last Run |
|----------|-------------|------------|----------|
| dafman17-1203 | 534 | pymupdf | 2026-03-06 |
| dafman17-1301 | 507 | pymupdf | 2026-03-06 |
| dafman17-1304 | 438 | pymupdf | 2026-03-06 |
| dafman17-1305 | 350 | pymupdf | 2026-03-06 |
| dafpam90-803 | 458 | pymupdf | 2026-03-06 |

---

## PDFs Available But Not Yet Indexed

Check `raw_pdfs/` against this list before ingesting to avoid re-processing.
All PDFs in `raw_pdfs/` as of 2026-03-08 are indexed above.
