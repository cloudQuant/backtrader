# Legacy CTP production configuration location

This directory is retained only for compatibility tests and migration review.
It is **not** the Iteration 41 operator configuration location, and it is not
registered as a runtime. Creating a `config.yaml` here cannot connect to CTP
or authorize trading.

The intended operator workflow uses the same protected file for SimNow and
future production CTP:
`examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`. Its
canonical `ctp:` block contains the account, contract and explicit MD/TD front
parameters. After SimNow acceptance, the future production switch will edit
that **same file**, set `runtime.mode: live` and
`runtime.preset: managed_live_direct`, and replace the CTP parameters with the
production account's values. The production admission, receipt, SDK artifact,
risk and recovery checks must still be implemented and accepted before that
configuration can run. Editing the file alone does not enable trading today.

The older `ctp_production:` parser remains only for compatibility tests. Both
internal production-config writer functions and the
`bt-runtime prepare-ctp-production-config` command now reject before reading
sources or creating a target. Do not use this
directory to maintain a production configuration. The shared `ctp:` parser
and same-directory pure production admission tests are the current migration
path.

Keep all private CTP configuration protected and excluded from Git. SimNow
approval material and production approval material remain independently
issued and scoped even though the configuration file and field shape are
shared.
