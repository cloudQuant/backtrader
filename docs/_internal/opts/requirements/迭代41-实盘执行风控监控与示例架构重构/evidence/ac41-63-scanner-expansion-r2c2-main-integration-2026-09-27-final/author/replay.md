# AC41-63 scanner and checklist expansion r2c

This patch is an isolated candidate. It preserves the source checklist's LF line endings and avoids a whole-file EOL rewrite.

From the repository root at the captured preimage, the deterministic check and replay are:

```powershell
git -c core.autocrlf=false apply --check --whitespace=error-all D:\temp\ac41-63-writer-dynamic-audit-20260927\candidate-r2c2.patch
git -c core.autocrlf=false apply --whitespace=error-all D:\temp\ac41-63-writer-dynamic-audit-20260927\candidate-r2c2.patch
```

Then run:

```powershell
python -m py_compile scripts/collect_iteration41_writer_inventory.py scripts/verify_iteration41_writer_dispositions.py tests/unit/scripts/test_collect_iteration41_writer_indirect_dispatch.py tests/unit/scripts/test_verify_iteration41_writer_dispositions.py
python -m pytest -q tests/unit/scripts/test_verify_iteration41_writer_dispositions.py tests/unit/scripts/test_collect_iteration41_writer_indirect_dispatch.py
ruff check scripts/collect_iteration41_writer_inventory.py tests/unit/scripts/test_collect_iteration41_writer_indirect_dispatch.py tests/unit/scripts/test_verify_iteration41_writer_dispositions.py
```

Expected result: 445 candidates and 445 REVIEW_REQUIRED / NOT_AVAILABLE dispositions; six focused tests pass. The first 389 checklist entries are byte-semantically preserved; their canonical record hash is frozen in `preservation.json`. The patch does not authorize writes.
