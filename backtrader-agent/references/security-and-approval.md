# Security and approval model

All external paths are represented as an opaque root ID plus a relative path.
Resolution rejects absolute paths, parent traversal, symlink escape, and
non-regular inputs. Dataset bytes are read with before/after stat checks and
stored in immutable SHA-256 CAS.

The AST validator does not import or execute candidate modules. It uses exact
module/alias, from-import, Backtrader API, local-symbol, OS, and environment-key
allowlists. It rejects dynamic execution, reflection (`getattr` and dunder
access), `open`, `pathlib`, process/network modules, product-runtime
transduction, live APIs, and path literals. A validation token binds the
artifact, dataset, environment, and engine hashes.

Apply and execution approvals are distinct. A change token cannot authorize a
run, and a run token cannot authorize a write. Each action follows persisted
`PENDING` request -> explicit local grant -> persisted signed token -> atomic
consume. Request creation and grant both recompute their context from the
current session checkpoint and an immutable, locally signed product record:

- Change approval requires the exact canonical prepared-change manifest,
  renderer-owned draft path, artifact/provenance record, spec, dataset, and the
  complete validation-token hash and ID. Apply reloads that signed record and
  does not trust a caller-supplied draft path.
- Run approval requires the exact signed applied-artifact record, applied and
  source artifact hashes, artifact provenance record, change manifest, spec,
  dataset, full validation-token hash and ID, and an allowlisted execution mode.
  Grant repeats these checks so a request cannot become valid after its backing
  state or signed record is changed.

A repeated idempotency/effect ID returns its existing result or resumes the same
journal, while any new effect fails after consumption. Expected target hashes
plus staged bytes, transaction journals, backups, and verified rollback prevent
partial multi-file writes.

The child process has a fixed argv, cwd, minimal non-inherited environment
without `HOME`, timeout, and resource/output limits. This is defense in depth,
not an OS sandbox or proof of network isolation.
