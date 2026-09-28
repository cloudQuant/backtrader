# G5 worker send-entry R2 evidence

**`R2_FAIL_CLOSED / G5 NOT ACCEPTED`.** R2 removes the caller-supplied sender from the public worker entry and defaults to a code-owned synchronous port that rejects before any native call when trusted time, projection provenance/readback, generation binding, or a reviewed SDK pin is absent. No provider order was accepted.

The Store command state `COMPLETED` in these logs means only that the local pre-entry rejection receipt was durably stored; its receipt outcome and worker handoff state are `REJECTED`. It is not a provider acknowledgement. The Backtrader bridge was not adapted to R2's sender-free API; any old-signature call fails closed. G5 and default managed CTP writes remain closed.

- [Frozen R2 candidate README](R2-CANDIDATE-README.md)
- [Output manifest](candidate-output-manifest.json) and SHA-256 `2b92b0a4d777221714f6b13f93eb9b39388993b4d0a585b35113d1eb4d6ed5e3`
- [R2 delta patch](G5_SEND_ENTRY_FAIL_CLOSED_R2.patch)
- [18-test implementation focus](r2-implementation-focus.log), [SDK candidate 53/4](r2-sdk-tests-candidate-source.log), and [frozen baseline 57/57](r2-sdk-tests-frozen-source.log)
- [R1 three-red source](r1-send-entry-regressions.py), [raw run log](r1-send-entry-regressions.log), [JUnit](r1-send-entry-regressions.junit.xml), and [copy hash receipt](r1-send-entry-regressions-copy-verification.json)
- [Complete raw candidate ZIP](r2-candidate.zip), SHA-256 `1ce285ed3e90f778ad05f55ded4263e522a54e04c7a20e3a5c30009bb298e283`; CRC and every manifest member hash were rechecked after copy.
- [Archive verification receipt](r2-candidate-archive-content-verification.json)
