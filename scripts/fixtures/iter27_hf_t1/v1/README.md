# Iteration 27 HF-T1 frozen inputs (v1)

This directory contains the tracked inputs used by
`scripts/run_iter27_hf_t1_independent_acceptance.py`.  The runner hard-pins
their SHA-256 values, copies them into each receipt, and records the checkout
and index state separately.

`fixture-provenance.v1.json` records the legacy observation artifact and the
only byte normalization applied while moving it into the repository.  The
current `source-observations.v3.json` records the rejected-tick risk-clock
repair; its v2 predecessor remains as historical provenance. In particular,
source-observation line numbers are historical planning provenance, not
assertions that an evolving checkout has unchanged line numbers. The harness
tests current behavior separately.

These fixtures are local planning and acceptance inputs.  They are not proof
of a sealed build, native CTP/SimNow execution, order/fill behavior, latency,
queue position, profitability, or HFT admission.
