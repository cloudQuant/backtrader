# OKX M01 V3 source candidate R1

Status: pending independent source/fake review. Scope is source and fake tests only; this packet establishes no account, provider, or case acceptance.

The bundle contains the exact 19-file production source map plus the focused V3 fake test. Both ZIP constructions were byte-identical. The source map document SHA-256 is `de8b619925353364b950b2f8beb97ccb5c7d5862868ff9665d081ba8afb83cdd`; the canonical source-pins digest is `78e84aee4ba39d02711bc6bd9f95f49871a81f20422af764e3d36a7dbdc96e78`.

The focused test result is 10 passed with one existing pytest configuration warning. Ruff, Black (`py311`, line length 100), and compilation checks passed. No `.env`, private account evidence, installed SDK, provider, network, or live harness was used.

The M01 route remains behind the exact protected deployment files under `D:/temp/iteration41-okx-m01-v3-deployment`. Root must create those files only after independent review.
