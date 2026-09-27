# Blocking scorecard

## Measured prior audit evidence

The supplied local audit measured normalised-name exact recall 21.85% at 21,868,489 train candidate pairs and normalised-address exact recall 8.28% at 770,877 pairs. These are descriptive baselines, not a selected candidate union.

## Current implementation status

Exact name, exact address, exact name+address and their deterministic union/provenance are implemented. Sparse character TF-IDF is implemented for a bounded target partition/sample. Rare-token, numeric-anchor and postal union stages remain explicitly unselected pending their population/block-size experiments; they must not be represented as measured or final.

## Blocking condition

At generation time the workstation had about 1.3 GiB available RAM and 6.1 GiB free disk. A conservative full exact-index estimate is about 6.6 GiB including write amplification and output headroom, while a complete token or character index is substantially larger. Resource guards therefore prevent an unsafe full run.
