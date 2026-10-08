# SimNow C01 V12 Root closure candidate R2

This public source candidate adds the bounded worker Job-count grace in V3 supervisor and corrects the V12 Root source-loader contract with a dedicated V7 front source loader. It pins the exact V12 issuer, owner/helper bundle, source manifest, schema, runner, front selector, and Root wrapper. The V12 runner now names the V12 issuer hash.

The payload contains the 19 rows of the V12 source manifest plus the manifest itself, V12 issuer, V12 case runner, Root wrapper, focused source-fake test, and V7 front loader (25 files total). Exact SHA-256 and byte counts are in payload-pins.json; source-payload.zip contains those exact bytes.

QA: 8 focused fake/source tests passed, with one existing pytest configuration warning, using the approved isolated QA interpreter, explicit repo and approved site-package paths, plugin autoload disabled, and a fresh repo .codex-tmp basetemp. No Root activation, provider login, SDK/native invocation, or actual transport was performed. Official C01 PASS remains 0.
