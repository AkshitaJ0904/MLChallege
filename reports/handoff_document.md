# Handoff to Akshita

No candidate configuration is selected yet. Do not train downstream scoring from the historical exact-only baseline.

When a candidate union is selected, consume optional provenance JSONL with these fields: `s1_id`, `target_id`, `target_source`, `candidate_channels`, `channel_count`, `retrieval_rank_by_channel`, `retrieval_score_by_channel`, and `country`. The official `candidate_pairs.tsv` remains a two-column list file and is not the rich feature contract.

Known current weakness: only exact retrieval is production-implemented; its supplied-audit recall is inadequate. Full lexical retrieval experiments require a larger scratch disk and more available RAM.
