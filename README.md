# Amazon ML Challenge 2026 - Business Entity Resolution

## Start here: current handoff to Akshita

| State | Verified handoff status |
|---|---|
| Current state | Train-side candidate-generation research and evaluation are complete. Real **test** candidate generation is pending. |
| Completed | Unicode-preserving preprocessing, exact and SQLite/postings lexical retrieval, candidate union/evaluation on train, deterministic folds and macro-F0.5 framework, and diagnostics. |
| Selected train retrieval | `exact_plus_lexical_default`; 52.1517% train target/candidate recall. This is not a test result or leaderboard score. |
| Stopped test work | The test lexical-index attempt was abandoned for excessive runtime. A later direct test exact-index fallback was also stopped. Neither produced a usable real test candidate export. |
| Current `candidate_pairs.tsv` | Emergency empty fallback only. It has one row per test S1 but contains no candidate IDs. **Do not use it for modeling, validation, submission, or as evidence that test retrieval is complete.** |
| Akshita starts with | Real test retrieval/candidate generation and validation, then pair modeling. |
| Do not redo | Do not rebuild, alter, or delete the completed train indexes/artifacts unless a concrete reproducible defect is established. |

This is the operational handoff. It separates verified train results from uncompleted test generation and planned matching work.

## 1. Project objective and outputs

The challenge is business entity resolution across three independent, noisy business sources. Each record has `entity_id`, `business_name`, `business_address`, and `country`, but there is no shared business key.

- **S1** is the deduplicated reference source. Every test S1 must appear exactly once in final output.
- **S2** and **S3** are target sources. For every S1, predict the complete set of matching target records.
- An S1 can have zero, one, or many S2/S3 matches. This is a set-prediction problem, not one-to-one assignment or source deduplication.

The final package needs UTF-8, tab-separated files in `output/`:

| File | Purpose |
|---|---|
| `candidate_pairs.tsv` | Final retrieval candidates given to the matcher. It must have `source1_entity_id` and `candidate_entity_ids`, one row for every test S1, and only valid test S2/S3 IDs. |
| `matching_results.tsv` | Final predicted match sets, with `source1_entity_id` and `matched_entity_ids`. This is the leaderboard-scored file. Final matches should be a subset of final candidates. |

## 2. Metric and implications

The official metric is macro F<sub>0.5</sub>: calculate set F<sub>0.5</sub> for each S1 and average over all S1s. Precision has twice the weight of recall. Empty/empty scores 1.0 for a true no-match S1; any false match for that S1 scores 0.0. False merges are therefore expensive.

The exact implementation is in `business_er.metrics.f_beta_set` and `macro_f_beta`; its tests cover empty and multi-match behavior. Evaluate decisions as S1-level sets, not pairwise accuracy or micro F-score.

## 3. Verified dataset audit

Direct line counts excluding headers verify **26,435,994 data rows** across the six source TSVs plus train ground truth (about 2.521 GB).

| Split | S1 rows | S2 rows | S3 rows | Source rows |
|---|---:|---:|---:|---:|
| Train | 2,206,821 | 5,034,616 | 5,285,603 | 12,527,040 |
| Test | 1,732,544 | 4,887,273 | 5,082,316 | 11,702,133 |

Train ground truth has one row per train S1 and **7,638,365 labelled links**: 3,693,619 S2 (48.36%) and 3,944,746 S3 (51.64%). The audit found no blank source fields, malformed ground-truth lists, duplicate targets inside a list, or unresolved ground-truth references. Exact duplicate source rows occur in S2/S3 but not S1.

### Cardinality, no-match, and country facts

- 123,247 train S1s (5.58%) have no match.
- Train cardinality counts for 0 through 11 matches are: 123,247; 119,157; 375,212; 530,841; 484,115; 321,957; 164,868; 63,968; 18,680; 4,205; 534; 37.
- Maximum total/S2/S3 targets per S1 are 11/5/6.
- 1,776,047 S1s link to both S2 and S3; 1,129,968 have multiple S2 targets and 1,224,128 have multiple S3 targets. One-to-many prediction is demonstrated by the data.
- Train contains India and US. Test adds France. Test country counts are S1 France/India/US = 259,452/809,986/663,106; S2 = 703,378/2,312,565/1,871,330; S3 = 731,615/2,405,000/1,945,701.
- All observed train links agree on country, but country is an **open-set string**. Do not hard-code `{India, US}` or reject France/other values.

### Text, exact, numeric, and postal observations

- Unicode is material: hundreds of thousands of S2/S3 addresses contain non-ASCII text. Probes found roughly 37-45% non-ASCII in India S2/S3 and 39-43% in France. Preserve Unicode; do not transliterate to ASCII.
- Audit exact coverage: normalized exact name recovered 1,668,793 links (21.85%), normalized exact address 632,211 (8.28%), and exact name+address 100,109 (1.31%). Exact retrieval is useful but insufficient.
- True-link overlap is common for name tokens (85.62%), address tokens (95.57%), and address numbers (79.88%). Numeric disagreement is not automatic non-match.
- Postal detection is deliberately postal-like: US ZIP, India PIN, and France five-digit patterns. In probes it was rare for India (0.01-0.02%) and France (0.42-0.59%) and around 10.23-11.14% for US. Postal/PIN is soft evidence, never a universal hard filter.

## 4. Problem findings and architecture

Naive S1-to-(S2+S3) comparison would require about 22.8 trillion train pairs and 17.3 trillion test pairs. Blocking/retrieval is mandatory. Exact matching alone has only 28.8043% train target recall, so candidate channels must be unioned and deduplicated by `(S1, target)`, not intersected.

Hard negatives include generic/brand-like names, legal-suffix variants, and same-name businesses at different addresses/states. True matches can differ through punctuation, legal suffixes, abbreviations, typos, reordered/omitted address components, missing number/state, literal `null`, numeric disagreement, transliteration/script variation, and occasional trade/domain-like names.

```text
S1/S2/S3 TSVs
  -> UTF-8 streaming + Unicode-preserving normalization
  -> exact blocks: name, address, name+address
  -> lexical postings: rare name, rare address, numeric anchor, postal soft
  -> union and deterministic de-duplication
  -> real output/candidate_pairs.tsv
  -> pair features
  -> matcher/ranker
  -> calibration + threshold/no-match/multi-match set decision
  -> output/matching_results.tsv
  -> validation and package
```

Candidate recall is a retrieval ceiling, not a matching decision, model precision, macro-F0.5 result, or leaderboard score.

## 5. Dhanush's completed train-side work

Completed code and evaluated train work:

- deterministic S1-grouped five-fold assignment stratified by country, match-cardinality bucket, and S2/S3 composition (`business_er.folds`);
- exact macro-F0.5 scorer and tests for singleton/multi-label cases;
- streaming TSV and disk-backed SQLite workflow;
- raw UTF-8 preservation plus NFKC, whitespace, punctuation/casefold, token, numeric, postal-like, length, and script views;
- optional country partitioning while preserving open-set country values;
- exact name, address, and name+address retrieval;
- SQLite/postings lexical retrieval: rare name, rare address, numeric/address anchor, and postal soft;
- deterministic candidate union/deduplication plus optional per-pair provenance;
- train recall, candidate-volume quantiles, S2/S3, India/US, singleton/cardinality, and no-match-candidate analysis;
- generic-name, Unicode, postal, hard-negative, and error-taxonomy diagnostics.

The deterministic fold framework exists, but no final fold-based pair-model result exists. The hard-negative taxonomy/interface exists, but no hard-negative training corpus has yet been generated.

## 6. Exact-only train retrieval baseline

The completed `exact_union` is exact name + exact address + exact name/address, deduplicated. These are **train retrieval** values only.

| Metric | Value |
|---|---:|
| Candidate pairs | 22,430,431 |
| True targets / recovered | 7,638,365 / 2,200,179 |
| Target recall | 28.8043% |
| Mean candidates per S1 | 10.16414 |
| p50 / p95 / p99 / max | 2 / 61 / 176 / 1,042 |
| S2 / S3 recall | 31.2205% / 26.5420% |
| India / US recall | 22.6937% / 32.8881% |

This baseline leaves 5,438,186 train targets outside the candidate ceiling and is not the final system.

## 7. Lexical retrieval and selected train configuration

The completed `artifacts/train_lexical.sqlite` is a SQLite/postings index, not a TF-IDF index. Its channels are:

| Channel | Key | Default retrieval cap |
|---|---|---:|
| `rare_name` | Least-frequent normalized name token | DF <= 50; up to 2 tokens |
| `rare_address` | Least-frequent normalized address token | DF <= 50; up to 2 tokens |
| `numeric_anchor` | Address-number token | DF <= 20; up to 2 tokens |
| `postal_soft` | Country-aware postal-like token | DF <= 100; up to 2 tokens |

The constrained version used one token/channel and caps 20/20/10/50. Exact and lexical candidates were unioned and deduplicated. The selected configuration is `exact_plus_lexical_default` because its volume met the report's selection rule.

**Character TF-IDF was not evaluated in the completed lexical run.** A bounded helper exists for samples/partitions, but no fitted full-corpus character index was built or evaluated. Do not state that character TF-IDF is part of the completed retrieval pipeline.

### Selected train result: `exact_plus_lexical_default`

All numbers are verified train retrieval/evaluation values from `reports/train_lexical_retrieval_report.json`.

| Metric | Value |
|---|---:|
| Candidate pairs | 43,917,636 |
| Target recall | 52.1517% |
| Recovered targets | 3,983,539 |
| Incremental recall over exact union | +23.3474 percentage points |
| Mean candidates per S1 | 19.90086 |
| p50 / p95 / p99 / max | 6 / 78 / 185 / 1,081 |
| S2 / S3 recall | 54.2475% / 50.1893% |
| India / US recall | 54.7245% / 50.4323% |
| Singleton-cardinality target recall | 51.9046% |
| Zero-match S1s with candidates | 81,103 |

Do not call 52.1517% a test result, final recall, macro-F0.5, or leaderboard score.

## 8. Current status: test retrieval is pending

Train exact retrieval was evaluated; train lexical retrieval was built and evaluated; the selected train configuration is exact + lexical default.

The test lexical-index attempt was started and abandoned because of excessive runtime. The later direct test exact-index fallback was also stopped. Incomplete artifacts remain as `artifacts/test_lexical.sqlite.partial` and `artifacts/test_exact.sqlite.partial`; they are not complete/readable indexes and do not represent successful test retrieval.

No test retrieval/indexing process is active at this handoff point. The existing `output/candidate_pairs.tsv` is only the emergency empty fallback. It must not be used as a final candidate result, feature input, submission artifact, or validation target. **Real test candidate generation remains pending.** Do not fabricate test recall or claim that test retrieval/final matching is complete.

## 9. Akshita's exact starting point and complete workflow

### Step 1 - Test candidate generation

1. Start from `dataset/test/test_source1.tsv`, `test_source2.tsv`, and `test_source3.tsv`.
2. Reuse the finalized `business_er.normalization` contract: raw UTF-8 preservation, NFKC, whitespace/punctuation/casefold, token, numeric, postal-like, length, and script views; country remains open-set.
3. Reproduce `exact_plus_lexical_default` where computationally feasible: exact name/address blocks plus unioned rare-name, rare-address, numeric-anchor, and postal-soft channels at the selected caps.
4. Generate real candidate S2/S3 IDs for every test S1. Channels are unioned and deduplicated; do not intersect channels or force one-to-one assignment.
5. Atomically replace the emergency file with the real `output/candidate_pairs.tsv`. Every test S1 needs exactly one row; an empty list is valid only when retrieval genuinely finds no candidate.

Never use train candidate IDs for test. Never assume the current empty fallback is usable.

### Step 2 - Validate the real candidate file

Check exact header/schema, UTF-8/tab formatting, malformed rows, duplicate rows, duplicate IDs within a list, missing test S1s, S1 membership, S2/S3 candidate-ID membership, and invalid prefixes. Use `utils/validate_submission.py` when matching output exists and use `--check-ids` when memory permits.

### Step 3 - Pair feature engineering

Build features only for validated final candidates:

- name and address similarity;
- numeric/address-anchor and postal/PIN agreement/missingness;
- candidate channel/rank/support indicators;
- missingness, ambiguity, cardinality, source, and open-set country features; and
- leakage-safe cross-source consistency where appropriate.

### Step 4 - Baseline matcher

Train Logistic Regression with deterministic grouped S1 folds. Use the exact macro-F0.5 implementation for evaluation.

### Step 5 - Stronger matcher

Train a regularized GBDT or appropriate tree-based comparator. Mine hard negatives from the actual candidate union, not random pairs only, and compare against the baseline on the same grouped folds.

### Step 6 - Decision layer

Calibrate probabilities, optimize thresholds for F0.5, add a no-match gate, and tune a multi-match/set-level policy. Preserve one-to-many matching; **never force one-to-one assignment**.

### Step 7 - Error analysis

Analyze singleton/no-match S1s, common-name false positives, address variation, typos/abbreviations, duplicate target records, multi-match entities, India/US/France behavior, and candidate-generation misses versus matcher/threshold errors.

### Step 8 - Final output

Generate `matching_results.tsv`, run final format and containment validation, and package reproducible code, the real final `candidate_pairs.tsv`, final matches, and methodology artifacts.

## 10. Artifact and file map

| Path | Status / purpose |
|---|---|
| `artifacts/train_exact.sqlite` | Completed train exact index. Keep untouched. |
| `artifacts/train_exact_manifest.json` | Train exact inputs, channels, checksums, and country setting. |
| `artifacts/train_exact_candidates.tsv` | Exact-only train candidate export. |
| `reports/train_exact_scorecard.json` | Authoritative train exact-union scorecard. |
| `artifacts/train_lexical.sqlite` | Completed train lexical postings index. Keep untouched. |
| `artifacts/train_lexical_manifest.json` | Train lexical channels and input checksums. |
| `artifacts/train_final_candidates.tsv` | Selected train `exact_plus_lexical_default` candidates. |
| `reports/train_lexical_retrieval_report.json` | Authoritative train channel ablations and selected result. |
| `artifacts/train_retrieval_eval_work.sqlite` | Existing train evaluation work DB; do not overwrite. |
| `artifacts/test_lexical.sqlite.partial` | Abandoned incomplete test lexical attempt; not a usable completed index. |
| `artifacts/test_exact.sqlite.partial` | Stopped incomplete test exact fallback; not a usable completed index. |
| `artifacts/test_pipeline.stdout.log`, `artifacts/test_pipeline.stderr.log` | Logs from abandoned test work; they do not establish success. |
| `output/candidate_pairs.tsv` | Emergency empty fallback only; replace after real test retrieval. |
| `src/business_er/cli.py` | CLI for folds, index build, exact export, and scorecards. |
| `src/business_er/retrieval_eval.py` | Read-only train union evaluation/export. |
| `src/business_er/candidates.py` | Exact/lexical indexes, union/provenance, bounded TF-IDF helper. |
| `utils/validate_submission.py` | Output-format and candidate-containment validator. |

## 11. Reproducibility and commands

The environment report records Python 3.11.9 on Windows and pinned dependencies in `requirements.txt`: NumPy, pandas, SciPy, scikit-learn, DuckDB, Polars, PyArrow, and psutil. Inputs are UTF-8 TSV and must be parsed with `sep="\t"`. The code streams source files and uses disk-backed SQLite to avoid materializing tens of millions of records in memory.

Run from the project directory with `PYTHONPATH=src`:

```powershell
$env:PYTHONPATH = 'src'

# Deterministic S1 fold framework
python -m business_er.cli make-folds `
  --source1 dataset/train/train_source1.tsv `
  --ground-truth dataset/train/train_ground_truth.tsv `
  --output artifacts/folds.tsv

# Exact index/export entrypoints; use a new controlled test work path,
# never overwrite completed train artifacts.
python -m business_er.cli build-exact-index --help
python -m business_er.cli generate-exact-bulk --help
python -m business_er.cli build-lexical-index --help
```

For real test retrieval, first plan sufficient disk/time and choose fresh test-only output/index paths. Do not append to the emergency fallback; write a complete replacement atomically. `business_er.retrieval_eval` is a train evaluation utility that reads existing indexes; do not overwrite `artifacts/train_retrieval_eval_work.sqlite`.

After both final output files exist:

```powershell
python utils/validate_submission.py `
  --matching output/matching_results.tsv `
  --candidate output/candidate_pairs.tsv `
  --test-dir dataset/test
```

`--check-ids` is optional and memory-heavy, but is the direct check that candidate/match IDs exist in test S2/S3.

## 12. Non-negotiable decisions and pending checklist

- Candidate channels are a **union**, not an assumed intersection.
- One-to-many matches are allowed. Never force one-to-one or a single argmax.
- Preserve Unicode/raw values. Do not transliterate to ASCII.
- Postal/PIN is soft evidence, not a hard universal filter.
- Country is an open set; do not hard-code India/US.
- Do not use external business lookup, registries, geocoding, APIs, or prohibited data augmentation.
- Do not equate candidate recall with final model quality. Exact-only 28.8% and selected 52.1517% are train retrieval metrics, not final system performance.
- Keep folds, IDF/frequency, hard-negative mining, calibration, and thresholds leakage-safe for grouped validation.

- [ ] Real test candidate generation from test S1/S2/S3
- [ ] Replace and validate the emergency empty `output/candidate_pairs.tsv`
- [ ] Pair-feature table
- [ ] Logistic Regression baseline
- [ ] GBDT/tree-model comparison
- [ ] Hard-negative training
- [ ] Calibration and F0.5 threshold/no-match optimization
- [ ] Multi-match/set-level decision policy
- [ ] Final `matching_results.tsv`
- [ ] Final validation and packaging/submission

## 13. Supporting project knowledge

- `reports/train_lexical_retrieval_report.json`: authoritative selected train retrieval result and ablations.
- `reports/train_exact_scorecard.json`: authoritative exact-union train baseline.
- `plan.md`: audit evidence, fairness constraints, modeling hypotheses, and experiments; distinguish its planned/older status statements from this current handoff.
- `reports/preprocessing_report.md`, `reports/postal_scorecard.md`, `reports/blocking_error_analysis.md`, and `reports/hard_negative_report.md`: supporting diagnostics and limitations.
- `README_PHASE0.md`: original retrieval-foundation notes; this README supersedes it as the current operational handoff.
