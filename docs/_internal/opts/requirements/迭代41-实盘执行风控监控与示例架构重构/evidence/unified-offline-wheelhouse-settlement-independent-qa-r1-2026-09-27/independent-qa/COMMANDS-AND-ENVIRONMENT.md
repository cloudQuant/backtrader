# Independent reproduction command and environment

Host: Windows x64; CPython 3.11.5 (`C:\anaconda3\python.exe`), pip from a new isolated venv.

Environment:

- `PIP_CONFIG_FILE=NUL`
- `PIP_NO_INDEX=1`
- `PIP_DISABLE_PIP_VERSION_CHECK=1`
- `PYTHONNOUSERSITE=1`
- `PYTHONDONTWRITEBYTECODE=1`
- New venv `include-system-site-packages = false`

Commands:

```powershell
C:\anaconda3\python.exe -m venv D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927\venv
D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927\venv\Scripts\python.exe -m pip install --no-index --find-links D:\temp\iteration41-unified-offline-wheelhouse-settlement-20260927-r1\wheelhouse --require-hashes -r D:\temp\iteration41-unified-offline-wheelhouse-settlement-20260927-r1\requirements-hashes.txt --report D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927\logs\pip-install-report.json
D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927\venv\Scripts\python.exe -m pip install --no-index --no-deps --force-reinstall --report D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927\logs\direct-root-install-report.json <four exact local root wheel paths>
D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927\venv\Scripts\python.exe -m pip check
C:\anaconda3\python.exe -B D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927\install_record_origin_audit.py
C:\anaconda3\python.exe -B D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927\artifact_static_audit.py
C:\anaconda3\python.exe -B D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927\base_source_compare.py
```

The full four-wheel direct install command, exact wheel paths, stdout/stderr, exit codes, install reports, audits and manifests are preserved alongside this file. All pip install commands explicitly disabled indexes; the initial 52-wheel pip report was independently checked for candidate-local file URLs and locked archive SHA-256 values.
