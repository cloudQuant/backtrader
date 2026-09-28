# CTP SimNow private-config readiness audit — 2026-09-23

`evidence_kind=plan_review`

This is a local, read-only readiness audit of file presence, schema shape, Git
ignore rules, and Windows ACL metadata. No credential values were recorded;
there was no SDK import, network access, or provider connection.

## Findings

- The Iteration 41 private `config.yaml` is absent from
  `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/`.
- That directory's `.gitignore` contains exactly `/config.yaml`,
  `/secrets.yaml`, `/calendar/`, `/reports/`, and `/state/`. Git confirms the
  private `config.yaml` path is ignored.
- The legacy ignored `.env` has `CTP_USER_ID` and `CTP_PASSWORD` fields, and
  both are empty. No other `.env` values are included in this note.
- On this Windows host, the Iteration 41 runtime directory and the legacy
  `.env` and tracked strategy `config.yaml` are rejected by the repository's
  protected-DACL checker (`config_yaml_windows_acl_invalid`). The private
  config file is absent, so its file-level ACL cannot be assessed; the current
  directory ACL alone would prevent the full gate from passing.
- The legacy strategy config contains a profile selector and automatic
  contract selection. Those Iteration 22 choices cannot be migrated
  automatically into Iteration 41. The private v4 config requires one
  operator-selected TD/MD pair and an independently verified current contract.
- No real provider read was performed or is available through the default
  registry: the private config is absent and no CTP SimNow private-read route
  is registered there. This note is local readiness evidence only, not provider
  or account evidence.

## Safe next step

After the runtime directory and new file meet the protected Windows ACL gate,
an operator can prepare the ignored v4 config locally using one explicitly
verified front pair and current contract details. Keep profile/calendar
selection out of the private runtime config.
