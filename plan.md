# Amazon ML Challenge 2026
# Deep Data Analysis and Winning Solution Plan

## 1. Executive Mission

Build a reproducible, local-only entity-resolution system that returns the complete set of S2/S3 records for every S1 reference entity, while maximizing the official macro F_0.5 metric.  This is an analysis plan, not a production build.

**Decision principle.** A high-confidence false merge is worse than a missed link under F_0.5. Candidate recall is a ceiling on final recall; pair scores must therefore be calibrated and decisions evaluated as per-S1 sets, including empty sets.

All statements below are explicitly marked **FACT**, **DATA OBSERVATION**, **INFERENCE**, **HYPOTHESIS**, or **EXPERIMENT REQUIRED**. No external business/entity information was used.

## 2. Official Constraints

- **FACT — README and validator.** Inputs and outputs are UTF-8 TSV. S1 is the deduplicated reference. Every test S1 must occur exactly once in `matching_results.tsv`; an empty list is the no-match prediction.
- **FACT.** S1 may match zero, one, or many S2/S3 records. A one-to-one assignment is invalid for this task.
- **FACT.** The leaderboard scores `matching_results.tsv` only, with macro F_0.5 per S1. Singletons score 1 only when the prediction is empty. Precision has twice the recall weight in F_0.5.
- **FACT.** The final package must contain both results and final-inference candidate files plus reproducible code/methodology. Final matched IDs should be candidates; the helper warns, rather than fails, on a containment breach.
- **FACT.** Test contains France although train contains only India and US. Country is an open string field; never train a closed `{India, US}` category rule.
- **FACT.** External business lookup, geocoding, and external augmentation are prohibited. Any final pretrained model must be MIT/Apache-2.0 and at most 8B parameters; verify the exact checkpoint licence before use.
- **FACT — `utils/validate_submission.py`.** Required headers are exact lowercase two-column tab-separated headers; duplicate S1 rows, duplicate IDs in a list, S1 targets, invalid prefixes, missing/extra S1 rows, and malformed lines fail. `--check-ids` is optional and memory-heavy; its absence does not make nonexistent targets valid.

## 3. Dataset Reality

**DATA OBSERVATION — full-file prior local audit, rechecked against file inventory.** Seven TSVs contain 26,431,994 data rows and about 2.521 GB.

| split | S1 | S2 | S3 | total |
|---|---:|---:|---:|---:|
| train | 2,206,821 | 5,034,616 | 5,285,603 | 12,527,040 |
| test | 1,732,544 | 4,887,273 | 5,082,316 | 11,702,133 |

**DATA OBSERVATION.** Every source has `entity_id`, `business_name`, `business_address`, and `country`. GT has one row per train S1 and a comma-separated target list. The prior full scan found no blank source fields, malformed GT lists, duplicate IDs inside GT lists, or unresolved GT references; exact duplicate rows occur in S2/S3 but not S1.

**DATA OBSERVATION.** Train country counts are India/US only. Test country counts are: S1 France 259,452, India 809,986, US 663,106; S2 703,378/2,312,565/1,871,330; S3 731,615/2,405,000/1,945,701.

**FACT.** A naïve S1 against (S2+S3) comparison is about 22.8 trillion train pairs and 17.3 trillion test pairs. It is not executable.

## 4. What the Audit Proved

- **DATA OBSERVATION.** There are 7,638,365 labelled train links: 3,693,619 S2 (48.36%) and 3,944,746 S3 (51.64%). All labelled links agree on country.
- **DATA OBSERVATION.** Normalized exact name captures 1,668,793 links (21.85%); normalized exact address captures 632,211 (8.28%); both captures 100,109 (1.31%). Exact keys are useful but cannot be the only candidate channels.
- **DATA OBSERVATION.** True-link token overlap is common: name 85.62%, address 95.57%, and address-number overlap 79.88%. This supports lexical candidates/features, not an exact-name-only model.
- **DATA OBSERVATION.** Unicode is material. Prior full scan found non-ASCII address text in hundreds of thousands of S2/S3 rows; a new 10,000-record per-country/source probe finds non-ASCII in roughly 37–45% of India S2/S3 and 39–43% of France records. ASCII-only normalization would destroy signal.
- **DATA OBSERVATION.** IDs are randomly ordered rather than merge-sortable. Full truth joins require a disk-backed/chunked design, not a naïve in-memory dictionary on this workstation.

## 5. What Remains Unknown

**UNKNOWN — REQUIRES EXPERIMENT.** The following have not yet been measured by a fully exact, held-out evaluation: union blocking recall/volume, TF-IDF top-K recall, pair-model F_0.5, calibration, source-specific thresholds, any embedding benefit, graph-consistency benefit, and France performance.

**UNKNOWN — REQUIRES EXPERIMENT.** Exact population postal candidate recall, collision precision, p95/p99 block size, and hard-filter loss remain open. The short postal probe below is evidence that this measurement is essential, not a substitute for it.

**UNKNOWN — REQUIRES EXPERIMENT.** Whether the observable S2/S3 cross-source graph adds independent information beyond their pair-to-S1 features.

## 6. Entity-Resolution Problem Geometry

**DATA OBSERVATION — full GT.** 123,247 of 2,206,821 S1s (5.58%) have zero matches. The total-cardinality distribution is:

| matches | S1 count |
|---:|---:|
| 0 | 123,247 |
| 1 | 119,157 |
| 2 | 375,212 |
| 3 | 530,841 |
| 4 | 484,115 |
| 5 | 321,957 |
| 6 | 164,868 |
| 7 | 63,968 |
| 8 | 18,680 |
| 9 | 4,205 |
| 10 | 534 |
| 11 | 37 |

**DATA OBSERVATION.** Maximum total/S2/S3 matches are 11/5/6. 1,776,047 S1s have targets in both S2 and S3; 1,129,968 have multiple S2 targets and 1,224,128 multiple S3 targets. This is a one-to-many set prediction problem, not record deduplication or bipartite assignment.

**INFERENCE.** Train separate candidate retrieval indices for S2 and S3, retain all calibrated positive pairs, and prohibit a global “one target can serve only one S1” constraint unless GT demonstrates it. Measure S1→S2, S1→S3, and joint cardinality distributions exactly during Phase 0.

## 7. Ground-Truth Behavior

**DATA OBSERVATION.** Labels include punctuation, legal suffix, abbreviation, typo, reordered/address-omitted, and domain/trade-name forms (for example, a labelled `Deneis Innovative Systems LLC` to `disystems.com` pair in the prior audit). Address noise includes reordered components, road abbreviations, missing house number/state, literal `null`, and numeric disagreement.

**EXPERIMENT REQUIRED.** Construct a reproducible train-only truth table keyed by S1 and target source, then report: exact S2/S3 cardinality histograms, S2/S3 conditional co-occurrence, duplicate-target reuse across S1, and connected-component sizes. These determine whether graph features are legal/useful and whether a component split is feasible.

## 8. Signal Forensics

| signal family | audit evidence | use | safety condition |
|---|---|---|---|
| normalized name equality | 21.85% true-link recall | high-precision candidate/channel feature | measure collision precision by country/source |
| normalized address equality | 8.28% | high-precision channel | never a sole acceptance rule |
| name/address token overlap | 85.62% / 95.57% true links | retrieval and continuous features | weight IDF; do not use English stopwords blindly |
| numeric overlap | 79.88% true links share an address number | pair feature and careful candidate channel | numeric mismatch is not automatic nonmatch |
| country agreement | all train links agree | partition and feature | keep open-set implementation |
| Unicode/script | substantial | preserve raw/NFKC-aware alternatives | evaluate raw and folded views, retain original |

**EXPERIMENT REQUIRED.** On grouped validation, compare true pairs with (a) uniform random cross-country negatives, (b) same-country lexical-top-K negatives, (c) same postal/address-number block negatives, and (d) candidate-generator negatives. Report distributions/AUC only as descriptive diagnostics; select by macro F_0.5.

## 9. Hard Negatives

**DATA OBSERVATION — local labelled example.** `S1-292935703` is `Cozy Grill`, 617 Fourth Street, Watseka, IL. GT lists six targets, including S2 `S2-617410789` (`Cozy Grill Corp`, 4TH STREET, Watseka). A local source scan finds numerous unlisted same-name `Cozy Grill` S2/S3 records at different addresses/states (for example S2 `S2-950430943`, Kansas City KS; S2 `S2-950417456`, Concord TN; S3 `S3-913557501`, Fenner NY). Because GT exhaustively lists that S1’s targets, these unlisted records are known negatives for this S1.

**INFERENCE.** Generic brand-like name, legal suffix, and even same state are unsafe acceptance signals. The matcher needs address-token/number/locality evidence, rarity-aware name evidence, candidate ambiguity, and a conservative decision threshold.

**EXPERIMENT REQUIRED.** Mine hard negatives from each successful channel by excluding GT targets, stratify by name similarity/postal/address agreement, and store no more than local IDs/features needed for diagnostics. Quantify frequency and false-positive contribution per bucket. Never create “random negatives only” training data.

## 10. Difficult True Matches

**DATA OBSERVATION.** Prior audit examples show suffix/punctuation changes (`Smart Malt LLC` / `Smart Malt-LLC`), suffix additions (`Ruby Pharmaceutical` / `Ruby Pharmaceutical LLP`), typo variants, and a trade/domain-like name. A local first-500-GT-row pilot also shows valid pairs with no detected ZIP/PIN on either side and omission-heavy records.

**EXPERIMENT REQUIRED.** Assign every held-out true link a mutually nonexclusive taxonomy: typo/edit, token reorder, suffix-only, abbreviation, transliteration/script change, domain/trade-name, missing address component, numeric disagreement, short/generic name, and Unicode normalization. Report each share, candidate recall by class, and post-score recall by class. A channel that fails a rare but material class must remain in the union or be replaced.

## 11. Postal/PIN Analysis

**Method.** The probe used country-specific *postal-like* regexes only: India `[1-9][0-9]{5}`, US `NNNNN` with optional `-NNNN`, France `NNNNN`; all had digit boundaries. This is deliberately not a claim that every hit is a valid postal code. Results are early-record 10,000-row country/source probes, not population estimates.

| split/source | India postal-like | US postal-like | France postal-like |
|---|---:|---:|---:|
| train S1/S2/S3 | 0.02% / 0.01% / 0.02% | 10.77% / 11.14% / 10.23% | n/a |
| test S1/S2/S3 | 0.00% / 0.02% / 0.02% | 10.67% / 10.62% / 10.40% | 0.42% / 0.59% / 0.56% |

**DATA OBSERVATION.** The India regex finds virtually no values despite many numeric addresses; those numbers are usually address components, not PINs. France postal-like values are also rare in this data. US ZIP-like values occur in only about a tenth of the probe records.

**DATA OBSERVATION — 500-S1/1,723-link order pilot.** Exact detected postal sharing among labelled US links was 36/479 S2 (7.52%) and 39/541 S3 (7.21%); it was 0/346 and 0/357 for India respectively. This is a diagnostic pilot, not a population estimate.

**Decision.** **REJECT as a global hard filter.** Postal is an optional, country-aware retrieval/feature channel: exact agreement is positive evidence; disagreement/missingness is normally soft evidence; a candidate must survive other channels. Postal + rare name token and postal + address-number are valid *experiments*, not assumptions.

**Phase-1 mandatory exact report.** For each source/country/key definition, stream-sort or use bounded disk partitions to measure coverage, true-link recall, target retrieval recall, candidate count, candidates/S1 mean/p95/p99/max, singleton/empty behavior, collision precision, and recall loss from a hard filter. Report union de-duplicated counts; never sum overlapping blocks as if unique.

## 12. Blocking Strategy Research

**FACT — literature.** Blocking/indexing exists to avoid comparing the huge set of unlikely record pairs; it necessarily risks false negatives, so its loss must be estimated ([Statistics Canada discussion of blocking loss](https://www150.statcan.gc.ca/n1/pub/12-001-x/12-001-x2021002-eng.pdf)).

**Design hypothesis.** Use a deterministic union of independently logged channels, source-specific and country-partitioned when country exists:

1. exact normalized name/address;
2. rare normalized name token and rare address token inverted indices, with max document-frequency caps;
3. numeric address anchor plus at least one rare lexical/locality token;
4. exact postal only as an additional channel where detected;
5. sparse character n-gram TF-IDF top-K on name, address, and combined text; and
6. optional dense retrieval only after lexical ceiling is measured.

**REJECT.** Broad common-token blocks, country-only blocks, postal-only global blocks, and any Cartesian expansion. Do not intersect channels unless validation proves the recall cost is negligible.

## 13. Candidate-Generation Design Space

| channel | likely solves | danger/cost | required measurement |
|---|---|---|---|
| exact normalized fields | formatting noise | low recall | recall and collision precision |
| rare name/address tokens | omissions and exact token overlap | frequent-token explosion | df cap sweep |
| numeric + lexical | address anchors | shared building/road numbers | hard-negative precision |
| postal + name/number | localized rows | sparse/absent fields | country-specific recall/volume |
| char TF-IDF | typos, punctuation, reorder fragments | sparse index RAM | recall@10/25/50/100/200 and index bytes |
| word TF-IDF/BM25-like | uncommon meaningful words | tokenization/script bias | same, by difficulty class |
| dense ANN | semantic/domain variants | licence, VRAM, false neighbours | incremental union recall |

**Acceptance gate.** A channel is retained only if it adds held-out true targets beyond the existing union at a predeclared candidate-cost budget. Measure exact deduplicated candidate union recall separately for S2, S3, India, US, and stress strata; France has no labels and is evaluated by transfer/structural diagnostics only.

## 14. Pair-Matching Design Space

**Architecture baseline.** Candidate pairs → cheap normalized/token/numeric features → supervised pair score → calibrated set-level selection. Positives are GT links. Negatives must be sampled from the actual candidate union and oversample hard negatives; use pair weights or sampling correction for the operational prevalence.

**FACT — Fellegi-Sunter.** The classical model frames comparison vectors as link/non-link evidence and explicitly allows match, nonmatch, and undecided decisions ([Fellegi & Sunter, 1969](https://nhis.ipums.org/nhis/resources/Fellegi69.pdf)).

**INFERENCE.** Use its log-likelihood-ratio intuition (rare agreement is stronger than common agreement) as interpretable features/baselines, not as an untested independence assumption. Compare: hand-weighted FS-style score, regularized logistic regression, GBDT, and GBDT plus calibrated decision policy.

## 15. GBDT Analysis

**FACT.** LightGBM supports binary classification and documents imbalance controls and calibration consideration ([official LightGBM classifier docs](https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.LGBMClassifier.html)); XGBoost exposes a `binary:logistic` objective ([official XGBoost docs](https://xgboost.readthedocs.io/en/latest/)).

**HYPOTHESIS.** A shallow/regularized GBDT on well-designed lexical, numeric, postal, missingness, retrieval-rank, and ambiguity features will capture interactions such as “generic name requires strong address evidence” better than a linear model.

**Controls.** Split before fitting IDF, frequency, target encoding, scaler, calibrator, or hard-negative miner. Use early stopping on a validation fold, constrain depth/leaves/min-child samples, inspect feature effects by source/country, and retain an out-of-fold score table. Do not treat raw GBDT scores as probabilities.

## 16. Embedding Analysis

**FACT.** Bi-encoders permit precomputed embeddings and fast similarity; cross-encoders score each pair and are more costly, which is why retrieve-then-rerank is common ([Sentence Transformers documentation](https://sbert.net/docs/quickstart.html)). FAISS is a dense-vector similarity-search library, with CPU/GPU implementations ([FAISS documentation](https://faiss.ai/)).

**DATA OBSERVATION.** Sentence Transformers is installed locally, but FAISS, LightGBM, and XGBoost are not. The GPU has 4 GB VRAM; disk free space was about 11.9 GB at audit time.

**Decision.** **DEFER.** Do not download/use a checkpoint until its exact licence, parameter count, offline reproducibility, and challenge permissibility are documented. Dense semantics trained on natural sentences may be weak for noisy business strings and could create high-similarity false merges. A cross-encoder is infeasible over millions of unfiltered pairs on 4 GB VRAM.

**Promotion test.** Only test a small compliant bi-encoder if lexical-union recall misses a measured class, and require incremental candidate recall at fixed candidate budget plus no degradation of grouped macro F_0.5 after reranking. A small character-level supervised encoder is a later comparator, not the default.

## 17. Logistic / Consensus Analysis

**HYPOTHESIS.** Logistic regression is valuable as an interpretable, regularized, calibratable comparator over monotonic/FS-style features. It may expose whether the GBDT gain is genuine.

**REJECT by default.** “GBDT and logistic must agree” is not a valid precision claim. It may simply discard correct rare matches and reduce recall. Test single models, calibrated score averaging/stacking using out-of-fold predictions, and AND gating. Keep consensus only if it improves macro F_0.5 and specifically reduces false merges on a locked stress fold.

## 18. Cross-Consistency / Graph Analysis

**DATA OBSERVATION.** 1,776,047 train S1s have both S2 and S3 links, so a local S1–S2–S3 triangle is possible.

**HYPOTHESIS.** For a high-scoring S1–S2 candidate, compatibility with a separately high-scoring S1–S3 candidate may help discriminate ambiguity. It can also double-count the same name/address evidence and propagate mistakes.

**Experiment.** First score only independent S1–S2/S3 pairs. Add leakage-safe features computed from out-of-fold predictions only: best other-source score, count of other-source positives, S2–S3 lexical compatibility, and score margin. Compare to the independent baseline on components withheld as groups. Promote only for incremental macro F_0.5; never let pseudo-links bootstrap themselves.

## 19. Set-Level Decision Strategy

**FACT.** The scorer macro-averages an F_0.5 per S1, so pair accuracy and global micro F-score are misaligned.

**Plan.** For each S1 retain every candidate above a calibrated pair threshold, then tune thresholds on OOF scores using the actual macro-F_0.5 implementation. Compare one global threshold, source-specific thresholds, country-conditioned thresholds with an “other” fallback, top-K caps, best-score/no-match thresholds, and margin rules. Do not force argmax: multi-match recall is material. A K cap is allowed only if validation shows it improves macro F_0.5 without systematically truncating true multi-match S1s.

## 20. Singleton Strategy

**DATA OBSERVATION.** 123,247 train S1s are known no-match. A false target changes their per-S1 score from 1 to 0.

**Plan.** Include all singleton S1s in every fold and candidate generation audit. Train candidate-level negatives from their retrieved candidates; derive S1-level features only from training/index data: maximum score, second-best score, margin, number above low thresholds, candidate-channel count, best name/address evidence, and candidate ambiguity. Tune a no-match gate directly for macro F_0.5. Never create candidates only for matched S1s.

## 21. France Strategy

**DATA OBSERVATION — local 20,000-France-record probes.** France has short names (median/p95 character counts: S1 19/29; S2 20/35; S3 20/36), address medians 48/40/41, common non-ASCII text (38.96%/42.79%/42.36%), and frequent legal/name tokens such as `sarl`, `sas`, `eurl`, `sasu`, and `sa`. Detected 5-digit values occur in only 0.42%/0.59%/0.56% of the probe. This is structural data analysis, not external French knowledge.

**Decision.** Preserve Unicode; apply country-agnostic character/token/numeric features; retain France as an unseen open-set branch. Do not use a learned France category or handcrafted external postal rules. Do not self-train initially: pseudo-label contamination would be especially dangerous under precision-heavy scoring.

**EXPERIMENT REQUIRED.** Simulate open-country transfer by withholding each observed country in turn, train only on the other, and evaluate country-agnostic versus country-conditioned features. Consider France pseudo-labeling only if a locked simulation shows a net gain after strict, independently verified high-precision seeds; otherwise reject it.

## 22. Train/Test Shift

**DATA OBSERVATION.** Test adds France, S1 test addresses are longer at the median (50 vs 41 in the prior full scan), and test S2/S3 have more non-ASCII text. Training S1 name median/p95 is 24/37 versus test 24/36; address patterns therefore shift more than name length.

**EXPERIMENT REQUIRED.** Produce train/test/source/country tables for missingness, raw and normalized lengths, script classes, digit and numeric-token counts, code patterns, token document frequency, legal suffix frequency, and channel candidate volumes. Use PSI/Jensen-Shannon or held-out classifier diagnostics as descriptive shift checks; do not interpret them as model scores.

## 23. Validation Strategy

**Primary split.** Deterministic 5-fold split by S1 ID, stratified by country, singleton flag, total cardinality bucket, and source composition. Build target indices, IDF, rare-token statistics, candidate mining, model, calibration, and threshold selection inside each training fold only. Evaluate full candidate sets and macro F_0.5 over all held-out S1s.

**Stress splits.** (1) country-holdout India↔US; (2) source-composition/cardinality strata; (3) connected-component grouping if target reuse/duplicate relationships create cross-fold paths; (4) a locked “generic name/high ambiguity” hard-negative suite. Random pair splitting is forbidden as a headline result because it leaks S1 topology and duplicate lexical evidence.

**Metric implementation.** Empty/empty must score 1; empty/nonempty and nonempty/empty score 0; otherwise compute set precision/recall and F_0.5 per S1 then average. Unit-test it against README examples and multi-match/singleton edge cases.

## 24. Leakage Risks

- **FACT/INFERENCE.** Random pair splits leak the same S1 and its related targets across folds.
- **INFERENCE.** Corpus IDF, token frequency, retrieval rank, target popularity, normalization dictionaries, and calibration fitted using held-out records leak test-fold distribution if globally computed.
- **INFERENCE.** Hard negatives sampled after looking at held-out labels, cross-source pseudo-links, and self-training can leak labels or reinforce errors.
- **Control.** Version fold assignments; use fold-local indices/statistics; retain raw record IDs only for joins; audit every feature for permissible inference-time availability.

## 25. Computational Architecture

**DATA OBSERVATION.** Audit machine: Python 3.11.9, 12 logical CPUs, 15.68 GB physical RAM, RTX 3050 Laptop GPU with 4 GB VRAM, and about 11.93 GB free disk. Available RAM was only about 0.68 GB during audit, so concurrent large jobs are unsafe.

**Plan.** Stream TSV with explicit UTF-8/tab parsing; partition intermediates by source/fold/country/hash; write compact Parquet only after confirming local storage budget; sort/merge partitions rather than materializing 12M Python objects; process S2 and S3 separately; use stable hashes and manifest checksums. Candidate rows should be deduplicated by `(s1,target)` before feature work. Cache only artifacts that can be reproduced and fit the disk budget.

**Budgets.** A float32 dense 384-dimensional embedding for 10M targets alone is about 14.3 GiB before an index—already infeasible here. Sparse TF-IDF must be measured with index bytes and chunked top-K retrieval. GPU is optional acceleration, not an architecture assumption.

## 26. Technology Stack

| tool | use / bottleneck | memory/risk | decision |
|---|---|---|---|
| Python + NumPy | orchestration/numeric features | Python object overhead | required |
| PyArrow/Polars | streaming TSV/Parquet | conversion disk cost | evaluate first |
| SciPy sparse + scikit-learn | char/word TF-IDF, cosine top-K, logistic/calibration | sparse matrix can still exceed RAM | primary lexical baseline |
| DuckDB | external hash/sort/join/aggregation | temporary disk may exceed 12 GB free | use only with budgeted partitions |
| LightGBM/XGBoost | tree comparator | not installed; dependency/reproducibility | install only after baseline and approval of disk/network needs |
| FAISS | ANN dense search | not installed; index memory | defer |
| Sentence Transformers | compliant embedding experiment | checkpoint licence/download/VRAM | defer |
| multiprocessing/joblib | independent partitions | multiplies memory | cap workers by measured RSS |
| rapidfuzz | edit features | not installed; per-pair CPU | optional, use only on finalists |

## 27. Feature Blueprint

| group | feature definitions to test | cost | leakage / rule |
|---|---|---|---|
| A. Name | raw/NFKC normalized equality, char n-gram cosine, edit ratio, token/IDF overlap, rare-token overlap, prefix/suffix, order, length ratio, legal-suffix flags | low–medium | fold-local IDF/frequency |
| B. Address | equality, token/IDF overlap, char cosine, order, locality-like overlap, length ratio | medium | do not require a parsed address |
| C. Postal | detected/missing/agreement/disagreement, block size | low | country-aware; soft by default |
| D. Country | equal, known/other/missing | low | open-set encoding |
| E. Numeric | any/exact/intersection/Jaccard, sequence/position, address-number agreement | low | distinguish all numbers from postal-like |
| F. Cross-field | name+address conjunctions, name+number, address+postal | low | test interactions, not manual acceptance |
| G. Retrieval | channel flags, rank, score, reciprocal rank, union support | low | index must be fold-local |
| H. Ambiguity | best/second score, margin, counts above bins, target/block frequency | medium | derive without held-out labels |
| I. Missingness | field/code/numeric missing flags | low | explicit rather than imputation |
| J. Cross-source | other-source score/count, S2–S3 compatibility | medium | OOF only |
| K. Graph | local triangle consistency/component stats | high | promote only after leakage audit |

## 28. Error Taxonomy

Every experiment must tag errors as: false merge; missed match; wrong S2 match; wrong S3 match; missed multi-match; false multi-match; false singleton; missed singleton; blocking miss; scoring error; threshold error; country-shift error; Unicode/script error; postal-code error; and ambiguous-name error. Attach source, country, cardinality, candidate channel(s), difficulty taxonomy, score/rank/margin, and whether the target was in the candidate union.

## 29. Akshita Proposal — Evidence Audit

| proposal component | verdict | evidence / risk / validation |
|---|---|---|
| country partition | **KEEP, modify** | all train links agree country; open-set “other” path required |
| multi-key union | **KEEP, test** | exact fields miss most links; log channel recall/cost |
| lexical/n-gram tokens | **KEEP, test first** | true token overlap is high; common-token explosion risk |
| numeric anchors | **KEEP, soft** | 79.88% true numeric overlap; shared/changed numbers are hazards |
| soft PIN key | **MODIFY** | sparse India/France and low US pilot recall; optional only |
| Stage-A then Stage-B GBDT | **MODIFY** | no evidence two trees beat one; compare cost/quality |
| learned embeddings | **DEFER** | no licence/benefit/RAM evidence yet |
| graph consistency | **DEFER** | topology supports testing, leakage/error propagation risk |
| GBDT + logistic consensus | **REJECT by default** | agreement can lose recall; require controlled gain |
| greedy per-target argmax | **REJECT** | violates documented one-to-many structure |
| conservative France self-training | **REJECT initially** | unseen-country contamination risk; require transfer simulation |

## 30. Alternative Architectures

| architecture | could solve | risk/cost | distinguishing experiment |
|---|---|---|---|
| A lexical union + simple classifier | strong transparent baseline | misses severe variants | grouped macro F_0.5 and block ceiling |
| B char/word TF-IDF + GBDT | typo/reorder retrieval + interactions | sparse RAM | recall@K and score ablation |
| C hybrid retrieval + calibrated GBDT | complementary channels, conservative sets | threshold overfit | locked-fold threshold test |
| D hybrid + embedding + GBDT | semantic/domain cases | licence/VRAM/false neighbours | fixed-budget incremental recall |
| E FS-inspired + ML | interpretable rare evidence | independence assumptions | compare calibration/error buckets |
| F two-stage retrieve/rerank | scalable rich scoring | stage-1 misses are irrevocable | union recall then rerank F_0.5 |
| G graph consistency | cross-source corroboration | leakage/propagation | OOF component stress test |

None is “best” before those experiments.

## 31. Recommended Experimental Sequence

| phase | experiment | success / stop condition |
|---|---|---|
| 0 | deterministic folds, metric, manifest, external partition join | exact reproducible macro F_0.5; otherwise stop |
| 1 | exact/rare-token/numeric/postal/TF-IDF candidate union | meet predeclared recall/cost curve; reject harmful channels |
| 2 | lexical/address/numeric feature ablations + hard-negative mining | reduce blocking/scoring error by taxonomy |
| 3 | logistic vs regularized GBDT | GBDT must beat baseline on locked fold |
| 4 | calibration, source/country thresholds, singleton/margin policy | net OOF macro F_0.5 gain, stable across folds |
| 5 | compliant embeddings | incremental fixed-budget value or reject |
| 6 | OOF cross-consistency | independent gain or reject |
| 7 | country-holdout/France robustness | no brittle closed-country dependence |
| 8 | frozen ensemble and full reproducibility run | validator pass and regenerated byte/accounting checks |

Log every run’s git/data hashes, fold, candidate counts, wall-clock/RSS, parameter file, threshold, macro F_0.5, precision/recall, singleton score, source/country scores, and error-table link. Use the public leaderboard only as one delayed noisy check after a local frozen candidate; never repeatedly tune to it.

## 32. Success Criteria

- Candidate union has measured high held-out target recall at a finite, stated p99 and total candidate budget.
- The selected policy improves mean macro F_0.5 on all primary folds and does not trade a gain for an unexplained singleton/generic-name collapse.
- The result is stable across S2/S3, India/US, cardinality, Unicode, and hard-negative stress reports.
- Full test inference fits the measured RAM/disk/time budget and produces valid, reproducible outputs.

## 33. Stop/Reject Criteria

Reject a channel/model when it adds negligible held-out targets per added candidate; increases false singleton/false merge rates; requires unsupported licence/external data; cannot fit the machine budget; depends on test labels/leaderboard iteration; or lacks a fold-local reproducible implementation. Stop broad feature accumulation if ablation cannot demonstrate incremental macro-F_0.5 value.

## 34. Final Production Architecture Candidate

**Candidate only — HYPOTHESIS.** An open-country, source-specific multi-pass lexical retrieval union (exact/rare token/numeric/char-TF-IDF) followed by a calibrated GBDT or logistic/GBDT-selected pair scorer, then macro-F_0.5-tuned multi-label/no-match decision policy. Preserve all final candidates and emit every test S1. Add embeddings/graph features only if the staged gates above demonstrate an independent gain.

## 35. Reproducibility Plan

Pin Python/dependency versions and model checkpoint hash/licence; version normalization, regexes, fold hash, feature schema, candidate channel configuration, threshold policy, random seeds, and data-file hashes. Make each stage resumable with manifest-based inputs/outputs. Add unit tests for TSV parsing, Unicode preservation, list de-duplication, candidate containment, macro-F_0.5 edge cases, and deterministic partition joins. Run the supplied validator before packaging.

## 36. Submission Checklist

- [ ] No external business data, geocoding, or unlicensed model.
- [ ] One tab-separated result row for each test S1; exact headers; empty singleton lists preserved.
- [ ] Only existing S2/S3 IDs; no duplicate IDs/rows; matches are final candidates.
- [ ] `candidate_pairs.tsv` reflects exactly the last candidate set scored.
- [ ] Reproducible code, pinned environment, methodology, experiment manifest, and model licence included.
- [ ] Run `python utils/validate_submission.py --matching ... --candidate ... --test-dir dataset/test` and, where memory permits, `--check-ids`.

## 37. Unknowns That Must Be Measured

1. Exact postal/PIN population tables and hard-filter loss.
2. Channel-union recall/cost and character n-gram top-K curves.
3. Pair-signal separation against channel-realistic hard negatives.
4. S2/S3 graph independence and component leakage.
5. Logistic/GBDT calibration, margins, source thresholds, and set selection.
6. Open-country transfer and any self-training net benefit.
7. Dense retrieval value after licence, parameter, and hardware feasibility checks.

## 38. Phase-2 Execution Plan

Start with Phase 0 rather than modelling: implement only a streaming audit/evaluation harness, an external partitioned GT join, grouped folds, and macro-F_0.5 tests. Next produce the exact blocking scorecard, beginning with country-aware postal diagnostics and lexical/token channels. Freeze a candidate union before classifier experiments. Train the smallest interpretable comparator first, then GBDT with hard negatives, then calibrate multi-label/no-match decisions. Treat embeddings, graph consistency, consensus gating, and France self-training as gated research branches, not promised components.

**Audit status:** Repository inspected: YES. Dataset deeply inspected with full-file prior audit plus new local probes: YES. Ground truth/cardinality: YES. Postal analysis: pilot YES, exact population scorecard pending Phase 0. Hard-negative evidence: YES. Train/test and France structure: YES. Computational audit: YES. General technical literature reviewed: YES. External business data: NO. Challenge data modified: NO. Production model built: NO. Submission generated: NO.
