# MIG01: remove the retired Backtrader Gateway implementation

Repository: D:/source_code/backtrader, existing dev checkout.
Parent: b9b226be6a82d91bdcb94bf29dfc1ccdad0611c5.

The old constructor aliases already rejected migration, but unreachable GatewayClient factory, environment loader and route branches remained in the shipped module. This round removes those implementations and their obsolete tests. Early legacy migration rejection, Direct and read-only Service entry points, and the direct/private typed CTP wrapper remain. The two CTP integration fixture changes only check that the obsolete factory is absent; those integration cases were not run.

Scope: five reviewed source/test paths plus this record. No SDK, provider package or unrelated worktree changes are included.

Acceptance: 25 focused tests passed in 3.63 seconds, exit 0, empty stderr, one existing unknown asyncio configuration warning. Exact command and raw outputs remain at D:/temp/iteration10-mig01-btapistore-gateway-retirement-author-r1. Root verified the saved output, candidate pins, exact diff and wheel; it did not repeat the accepted tests. Independent static review accepted the five paths and scanned all 592 wheel Python members, with no old GatewayClient/import/factory/environment-loader references. One nonfunctional CTP wrapper docstring still contains the word Gateway.

This is source/component and candidate-wheel evidence. It does not by itself establish final MIG01 isolated installed-wheel acceptance, Host behavior, account/provider acceptance, or a formal case increase. The separately committed M6 evidence remains valid for its fixed inputs. A fresh affected Backtrader installed-wheel check follows this commit.

Exact reviewed diff: 35843 bytes, SHA-256 2a893ef3db41a76b1bfbaae8f1262f2993bd8f545cefaeff1342e4604bde1114.
Author stdout SHA-256: b66ee7a48a171097b01c8417c51c86fecb11043e7fcb67ed585febccd4702fbd.
Wheel: D:/temp/iteration10-mig01-btapistore-gateway-retirement-wheel-r1/backtrader-1.4.0-py3-none-any.whl, 2119263 bytes, SHA-256 bde268fe314b23c0ca22bbdb9ea228e312457639e619bfa4230cf177a57dce43.
Wheel scan SHA-256: 98467d40f4e005590b91f577b06b31e661b40c3caf2bcc5a35e12a968a28a1cf.

Reviewed checkout source pins (Git may normalize existing line endings):

- `backtrader/stores/btapistore.py`: 782916 bytes, `62c5abbb6b4b7105cfd8ced2ad56927020fcb0dd28d686a443f0d0706a761a66`.
- `tests/integration/test_ctp_options_highfreq_native_broker_chain.py`: 26827 bytes, `e5475f6efa8aab397554964ea60219c8be79b2a92da63741eaae33c42a651cbe`.
- `tests/integration/test_ctp_options_lowfreq_native_broker_chain.py`: 77257 bytes, `be5390e8bd3ea9730b38834d1c94fbddf3618094bf6f42495b18770227e5d629`.
- `tests/unit/stores/test_btapistore.py`: 141749 bytes, `ddcfe44a6722bac89470b60308928617c9898ad2c8548779918ed7be7a249746`.
- `tests/unit/stores/test_btapistore_legacy_gateway_retired.py`: 5579 bytes, `e0814241443180efe62ce93c2a3043e187e5c14448f2aef61ef9256dfd1320c7`.
