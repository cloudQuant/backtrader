# Iteration10 ARB06 closed-group Host acceptance

Existing Backtrader `dev`, QA parent
`884c3d4de44d0a72cce907344b4f028574c9d2e0`; SDK QA parent
`954b78b1ca657a3eb68a155eca77259c5008a074`.
Scope: this record and the two integration test/fixture files below.

Root R10 passed the complete node once: **1 passed, 2 warnings, 17.60 s,
exit 0**, empty stderr. All 901 fixed source pins and eight repository HEADs
were unchanged. Warnings were the existing Quandl deprecation and Windows
ZMQ Proactor/selector compatibility warning. Output:
`D:/temp/arb06-full-close-committed-r10-20261017/host-output-r10/`.
Spec SHA-256: `6943c79545e3a8db25e875adb0b98bbdcad4b6da40c31db3c1324ce9c6c7af0b`.
Stdout SHA-256: `87d724fefd7793be1692e837fa93e4c842d067c40af6598230b3f60fa31b4f0f`.

Accepted source SHA-256:
- `tests/integration/test_arb06_group_roll_exit_closed_cerebro.py`:
  `e27c347236d2135a6561cb1c0fcef717459e959c6a366b364a4a010e4d900d6a` (64,645 B).
- `tests/integration/_arb06_two_leg_roll_exit_risk_fixture.py`:
  `42ec7e52e44d9a796fb27d6f194175b988535a643e9d5c14a16a9ea2411a8640` (62,737 B).

Two real Cerebro strategies use Store/Broker and Gateway/Risk/Coordinator
services with synthetic provider leaves. The seeded account and Coordinator
processes close before the four service Host threads run. The additional
reservation Host borrows the existing accepted store; its standard registration
advertises reserve/query/release, while a transparent spy proves actual calls
only query. It closes and joins before the shared Risk resources are cleaned.
All service/session/runtime cleanup assertions passed; the final fixture receipt
reports both owner threads joined/closed, no cleanup failures, and one resource
cleanup. No account or native venue call is represented by this evidence.

The source position closes from 1.5 to zero while the same-account peer retains
0.75. Account quantity moves from 2.25 to 0.75; cash/equity move from
9850.05/10075.05 to 10001.60/10076.60. Sizer uses cash, peer group-route access
is denied without a provider effect, exactly two CLOSE dispatches resolve/fill,
and replay adds none. The persisted group is CLOSED with zero residual,
reservations/budget RELEASED, and a validated close proof binds both source
legs, fills, fees and release evidence.

The closed node makes no Monitor calls. Formal ARB06 combines this result with
the accepted R169 Monitor relay evidence in SDK commit `dcad4003`, at
`docs/迭代计划/迭代10-可选组件与可配置通信/evidence/arb06-group-monitor-relay-20261016/root-adjudication.md`.
That evidence covers durable group.residual delivery and idempotent polling;
its recorded multi-portfolio journal limitation remains disclosed.

R7/R8/R9 failures remain preserved: invalid fixture binding fields/alias,
scale-sensitive monetary text comparison, and lower-case enum comparison.
The repaired assertions retain exact numeric value and typed side checks.
Production source is unchanged by this Backtrader round. Accepted R18 support
variants are inherited and not recopied; no 901-file source archive is added.
Independent static reviews covered the fixture and final deltas. R10 is not
repeated for delivery. The commit containing this record identifies the
accepted Backtrader revision; the SDK formal record cites that revision.
