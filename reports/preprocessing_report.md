# Preprocessing report

## FACT

The pipeline preserves raw UTF-8 business name/address/country strings and derives NFKC, whitespace-normalized, punctuation-aware case-folded, token, numeric, postal-like, length, and script views in `business_er.normalization`. It does not transliterate to ASCII, remove digits, or overwrite raw values.

## DATA OBSERVATION

The supplied audit reports material non-ASCII records and test-only France. Country is retained as its raw open-set string; India/US/France/Other buckets are diagnostics only.

## EXPERIMENT REQUIRED

Compare all normalization views by held-out candidate recall and candidate cost before selecting a production blocking key.
