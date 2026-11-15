# P2a label-v2 data gate

**Status: blocked (`passes: false`); checked 2026-11-15. No v2 labels were generated and no training was started.** The real Drive-derived OHLCV files have now been retrieved from the public P1 HF repository. The remaining blocker is adjusted total-return semantics and incomplete corporate-action/universe history, not the missing 2014–2016 price source.

## Verified raw source

The four supplied files are under [`raw-2014-2026/`](https://huggingface.co/datasets/Jerlob/vn-stock-ai-p1/tree/main/raw-2014-2026). Their top-level metadata declares `finfo-vndirect(2014-2016)+finhay-fhsc(2017-2026)`. Actual OHLCV rows run 2014-01-02 through 2026-11-06; the schema is only `date,open,high,low,close,volume` per ticker. No adjusted-close field is present.

| Exchange file | Tickers | OHLCV rows | Observed sessions | Source SHA-256 |
| --- | ---: | ---: | ---: | --- |
| HOSE | 432 | 1,132,961 | 3,204 | `5126fc62f1210b0b4cc4bc5c4843e4f007a89376ea935ed387407c8950f09395` |
| HNX | 299 | 871,616 | 3,204 | `0ef3b7f06d5e2c60fc64b90504b8441da94e4121ea02734c3c5c943aad2c21d3` |
| UPCOM | 809 | 1,916,394 | 3,204 | `3f018dab0f2a8ecbac0409bca307971b089c69c8abbaecf5e70f46b64ce8f219` |
| OTC | 24 | **0** | **0** | `4d2a42e1e0c8156f0e3a509ec5188b1ab96945b3e308d26536600de44778902c` |

The raw files total 3,920,971 rows. Normalization removed 1,030 all-zero UPCOM placeholders, retained closes, and flagged 5,937 OHLC-order mismatches (HOSE 1,119; HNX 401; UPCOM 4,417). The resulting observed-only session file has SHA-256 `eb43751c92bdce88ef0213d280524a439d200ebe290529111b1c03df043cda10`. No weekday-derived dates were added. There are no P1 OTC examples, and all 1,322 P1 tickers have at least one valid raw close in their exchange partition (HOSE 414, HNX 296, UPCOM 612).

The observed calendar fixes the prior 13,062 missing `as_of` dates from 2014–2016: **all now map to an actual observed session**. Against exact 120th-future-session endpoints, raw start/end quotes exist for **83,832/83,942 train** and **13,816/13,824 holdout** rows; 110 train and 8 holdout endpoint quotes are missing. No source `adjusted_total_return_close` exists, so these remain raw-close diagnostics only. With a ±2% diagnostic band, observed raw labels are train DOWN 37,683 / FLAT 6,145 / UP 40,004, holdout DOWN 6,900 / FLAT 1,497 / UP 5,419. Compared with the old P1 label, 10,508 train and 1,884 holdout directions differ; this is expected evidence that the old row-shift labels need rebuilding, **not** a final label result.

For the overlapping period 2017-01-03–2026-11-06, the Drive-derived dates match Finhay index dates on HNX and UPCOM (2,458 each). HOSE has 2 additional actual stock-price dates (2018-01-23, 2018-01-24) missing from the Finhay index file. Finhay's index files extend 5 sessions beyond the Drive snapshot through 2026-11-13. See the full aggregate and source checksums in [[file:docs/p2a-drive-source-audit.json]]. The normalized raw tables are temporary files under `/tmp/p2a-drive-source/normalized/`; market rows were not committed or uploaded.

## Adjustment and survivorship gate

The Finhay source snapshot has 3,001,106 cleaned price rows but **0** adjusted total-return closes. Its corporate-action snapshot has 11,027 events. The earliest cash-dividend event is 2022; stock-dividend/bonus/rights records start in 2023. Of 3,182 cash dividends, 724 lack an amount; 15/220 bonus-share and 42/530 stock-dividend records lack complete ratios; 23/160 rights offerings lack a right-to-share ratio and subscription price. The [Finhay event reference](https://developers.fhsc.com.vn/api-reference/tin-tuc-su-kien/su-kien-quyen-cua-stock) specifies event fields but not complete historical coverage or a total-return adjustment formula. The [historical-price reference](https://developers.fhsc.com.vn/api-reference/bang-gia-thi-truong/lich-su-gia-co-phieu) defines OHLCV bars and does not promise adjusted values. Therefore the action snapshot cannot safely backfill earlier actions or prove a complete total-return series.

The requested HF dataset `datnkhptit/vn-stock-ohlcv` is gated (`auto`, license `other`); the existing HF token was rejected with `GatedRepoError` HTTP 403 in workflow `43685488389`. No gate terms or profile sharing were accepted. Its public metadata lists 144 P1 ticker directory overlaps but only 87 P1 silver-file paths. A separate ungated public repo `Trung2710/vn-stock-ohlcv` has 55 symbols and 50 P1 ticker overlaps (3.78%); a temporary local schema check found 140,815 bars with `close_adj`, but no license is declared and the exchange column is null for every row. It is not a complete or verified replacement.

The Drive API itself still returns HTTP 403 because the OAuth caller lacks `serviceusage.services.use` on quota project `764086051850`; this no longer prevents reading the four supplied files from their HF mirror. For the gated HF dataset, an HF account holder must explicitly accept its access terms before the configured token can read it. Google quota guidance: [Troubleshoot ADC](https://docs.cloud.google.com/docs/authentication/troubleshoot-adc).

## Current disposition

The real OHLCV source fixes the calendar/coverage problem, but step (1) is **not passed**: adjusted total-return labels and point-in-time listing/universe evidence remain unverified. Do not relabel raw close as total return. Use the observed calendar and preserve/censor exact missing quotes; keep labels provisional until action adjustments and their coverage are validated. The training code rejects v1 labels, and no train/smoke-train was run.

The earlier Finhay-only weekday calendar is superseded and must not be used. All evidence is summarized in [[file:docs/p2a-progress-24.md]].
