# Candidate-generation foundation

This package owns retrieval only: preprocessing views, grouped folds, exact/lexical candidate channels, candidate provenance, scorecards, and hard-negative interfaces. It does not train or apply a matching scorer.

Run with `PYTHONPATH=src python -m business_er.cli --help`.

All input reads are UTF-8 TSV streams. Derived data is separate from `dataset/`. `candidate_pairs.tsv` follows the official two-column schema, while optional provenance JSONL supplies Akshita's richer pair contract.

## Resource policy

`build-exact-index` estimates at least 550 bytes per target row and refuses to start unless 25% additional free disk remains. The current workstation does not have capacity for a full lexical or char-TF-IDF index; run full stages only after attaching sufficient local scratch storage. Do not bypass the guard except in a measured disposable pilot.

## Reproduction sequence

```powershell
$env:PYTHONPATH='src'
python -m business_er.cli environment-report --output reports/environment_report.md
python -m business_er.cli make-folds --source1 dataset/train/train_source1.tsv --ground-truth dataset/train/train_ground_truth.tsv --output artifacts/folds.tsv
python -m business_er.cli build-exact-index --targets dataset/train/train_source2.tsv dataset/train/train_source3.tsv --estimated-target-rows 10320219 --index artifacts/train_exact.sqlite --manifest artifacts/train_exact_manifest.json
python -m business_er.cli generate-exact --source1 dataset/train/train_source1.tsv --index artifacts/train_exact.sqlite --output artifacts/train_exact_candidates.tsv --provenance artifacts/train_exact_provenance.jsonl --manifest artifacts/train_exact_generation.json
```

The final test candidate file must be generated only after measured union selection; this package never creates `matching_results.tsv`.
