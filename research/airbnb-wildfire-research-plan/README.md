# Price Protection, Stay-Length Rules, and Consumer Access

Research plan and reproducibility starter. Version 2.0 plan / version 1.0 starter, 2026-10-13.

## Status

- The HTML is a research plan, not a new LA regression report.
- Literature-derived findings, project-reported findings, proposed hypotheses and software tests are separate.
- `run_stay_plan.py` was executed twice on explicitly synthetic fixtures. All 8 checks passed; 14 deterministic output files matched across runs. Time-stamped run manifests were excluded from byte comparisons.
- No new raw LA archive was analyzed for this release. No claimed host response, p-value or consumer outcome is supported by the synthetic tests.

## Tested environment

Python 3.11.9; numpy 1.26.0; pandas 2.1.1; scipy 1.11.3; statsmodels 0.14.6. The archive metadata audit needs only the standard library. Statsmodels is optional for analysis but required for the independent covariance cross-check in `selftest`. Record the actual environment when reproducing; installation success on every operating system is not guaranteed.

## Commands

```sh
python run_stay_plan.py selftest --out outputs/synthetic_test_01
python run_stay_plan.py audit /path/to/wildfire_full_data_results_20261009.zip --out outputs/archive_audit_01
python run_stay_plan.py analyze canonical_panel.csv --config design.json --out outputs/main_unweighted_01
```

Output directories must be new. Input files are never modified. Archive audit does not extract members, execute contained code, infer dates from filenames, or emit review bodies. Keep a real archive manifest restricted because filenames can contain sensitive information.

## Required human-validated input

A UTF-8 CSV with one row for every fixed-cohort listing and every actual source snapshot:

```csv
listing_id,snapshot_date,present,minimum_nights,maximum_nights,treated,hex_id,weight,coverage_ok
```

1. Construct the cohort using the project's locked pre-fire rule and log every exclusion.
2. Verify source-period coverage before supplying explicit absence. The starter refuses an incomplete grid; it never silently fills missing rows with zero.
3. Keep unknown rules missing. Zero cannot represent a missing minimum stay. Rules are valid only for finite positive integers with maximum >= minimum.
4. Preserve exact date provenance. Calendar stay dates are not dates on which the rules were observed. The example configuration intentionally contains no fabricated LA observation dates.
5. Treatment, hex and weights must be fixed per listing; treatment is constant within each hex. Use the original exposure/coordinate pipeline, not rounded geography invented for this starter.
6. Supply a separately audited, pre-treatment fixed unit weight, or use 1 for a labeled unweighted baseline. The starter does not fit synthetic weights and does not validate their causal comparability.
7. Replace the empty dates and all REPLACE explanations in `design_template.json`; save as `design.json`. Supplying text is not proof that the documented assumptions are true.

## Fixed protocol

Primary platform threshold K=28. Primary family: `flexible` and `long_only`, with Holm adjustment for these two pooled contrasts. K=30 and K=31 are predefined sensitivity definitions, not additional opportunities to select a favorable result. Other mutually exclusive states are diagnostic.

States: absent; visible but unknown/invalid rule; short-only; flexible; long-only. They partition the same risk set. The output checks that pooled state effects sum to zero.

The estimator regresses individual post-minus-pre mean outcome on an intercept and treatment, with supplied fixed unit weights. With a balanced panel and equal snapshot weights within pre/post periods, its coefficient agrees with the corresponding two-way fixed-effects contrast. Inference is a conventional hex-cluster CR1 benchmark conditional on those weights. It is not spatial HAC, few-fire inference, IPCW, HonestDiD or standard Synthetic DID. It does not propagate estimation uncertainty in fitted weights.

## Outputs

- `did.csv`: all state estimates, conventional CR1 intervals and p-values; the two main K=28 contrasts receive Holm adjustment.
- `event_study.csv`: date-specific comparisons against the locked pre-fire reference. Intervals are pointwise; the reference is a fixed zero.
- `state_shares.csv`: group-by-date state counts and weighted shares.
- `transitions.csv`: adjacent-snapshot transitions with a fixed-group denominator, not a selected conditional causal return probability.
- `did_vcov_k*.csv`, `event_vcov_k*.csv`: complete covariance matrices for explicitly named contrasts.
- `run_manifest.json`: code/input/config SHA-256, versions, dates, sample size, clusters, effective sample size, January policy-column diagnostic and limitations.

## Interpretation gates

- Three distinct policy columns are necessary for time-only separation, not sufficient for causal identification. Identical columns for January 7/15/27 cannot produce separate policy effects.
- An increased share of monthly-only listings can be caused by changing composition. Inspect same-listing transitions and the full risk-set states.
- Rule changes do not establish actual bookings, guest disaster status, habitability or housing-use conversion.
- A price-cap announcement is not demonstrated implementation or compliance.
- Public text does not identify actual motives or payment arrangements.
- Already-inspected historical data analyses are exploratory. A prospective protocol can be frozen before additional analysis, but cannot retroactively become an untouched preregistered test.
- Keep all null, reverse and inconclusive results. Passing software tests never implies a significant or true research hypothesis.

## Publication and privacy

Only the research plan, general code, a blank design template and synthetic verification record are public. Do not commit source ZIP files, listing-level panels, guest comments, precise residential coordinates, identities or access credentials. Real-data results require explicit review before public release.
