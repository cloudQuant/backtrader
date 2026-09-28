# G4 pinned base/CTP wheel rebuild: independent QA

**Disposition:** `SOURCE_PROVENANCE_MATCHED_AFTER_EOL_NORMALIZATION / EXACT_CTP_PIN_REBUILD_NOT_PROVEN / NO_INSTALL_OR_NATIVE_ACCEPTANCE`.

This read-only QA used only the isolated artifacts under this directory plus source inspection of the two external SDK repositories. No private config, account, provider, native import/session, or successful network connection was used. The main backtrader tree and SDK source trees were not edited. No code-owned pin or default route was changed.

## Pinned source and artifact identities

- Base source: `D:\c41sdkf\bt_api\bt_api_base`, clean `HEAD 73e860e2fd8086ec817db254d4c396c2a76eb7d6`, declared version `0.15.5`.
- CTP source: `D:\c41sdki2\bt_api_ctp`, clean `HEAD 28157ce33009f932fbf8b3a78f7e77cb42c9cc4b`, declared/public version `2.0.3+iteration41.i2`.
- Main-tree code-owned wheel pins were read from `backtrader_runtime/ctp_artifact_provenance.py` (file SHA-256 `78f7b385db4c33f522a645e160b23076d7b600cf539cf6a121897483c49b3c75`): base wheel `1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d`, CTP I2 wheel `988c52a91a12d3256caadf27df2ae1f1eb45e54fc6c4f63b7abba0363f34c4ff`.
- Frozen source archives were `bt_api_base-0.15.5-73e860e2fd8086ec817db254d4c396c2a76eb7d6.tar` (`62dad9c535de47613a15a0e4f64f7af85682628a82c2543649bc723c5ca73f80`) and `bt_api_ctp-i2-28157ce33009f932fbf8b3a78f7e77cb42c9cc4b.tar` (`9005a1754210d1dacb02eb1545d2c0718c1fdfd08ee62141566fae4181194821`). The archive member names exactly matched each commit tree (191/191 base and 260/260 CTP), with zero missing, extra, or other-content mismatches after CRLF-to-LF normalization. The pinned wheel Python members also matched the corresponding Git blobs after that same normalization (105/105 base; 78/78 CTP).

## Independent offline builds

Two separate build roots, `build-a` and `build-b`, were built from those source snapshots. Both base and CTP wheel commands exited 0. They used Python 3.11.5, pip 23.2.1, setuptools 65.5.0, wheel 0.43.0, MSVC/link 14.42.34433, and `pip wheel --no-index --no-deps --no-build-isolation --no-cache-dir`.

| Artifact | Build A SHA-256 | Build B SHA-256 | Code pin SHA-256 | Outcome |
|---|---|---|---|---|
| base 0.15.5 | `0d16a7770ea6e17c862b88a085c71b88e60649c549a87d95a5cf9c751c5dec8a` | `3c09d7d9b6ba6421cf9f9c683cca34a47358e9df9cbb313b88f858916058c779` | `1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d` | A/B wheel hashes differ; all 110 payload members and embedded `RECORD` are identical to the pinned wheel. Only ZIP timestamps differed. A diagnostic copy made from build A by replacing local and central ZIP timestamps with the pinned wheel's timestamps exactly matched the pinned SHA. This shows content identity plus timestamp-only container difference; it is not an independent reproduction of the missing original timestamp recipe because the existing pin supplied that recipe. |
| CTP `2.0.3+iteration41.i2` | `7759a11487ddb0067e3fb755366c989b1fe55a965f3d712526d59b6bb228817d` | `1de546d5c18b439d77d26dd0039e08b4facbbeaf1b0b865a38eafa211c2d46f8` | `988c52a91a12d3256caadf27df2ae1f1eb45e54fc6c4f63b7abba0363f34c4ff` | A/B not byte-identical. Of 87 members, their only payload differences were `_ctp.cp311-win_amd64.pyd` and `RECORD`; the native member differs at six byte positions, including the PE COFF timestamp (`A 0x6ab8f82c`, `B 0x6ab8f8d9`; pinned `0x6ab5394d`). Against the pinned wheel, four payloads differ: `RECORD`, `_ctp.pyd`, `bt_api_ctp/__init__.py`, and `bt_api_ctp/ctp/client.py`. The two Python differences are line-ending-only: rebuilt files are all CRLF; the pinned files contain mixed CRLF/LF. The native binary differs at six byte positions; the second three-byte site was not fully decoded. ZIP timestamps also differ. Exact pinned CTP wheel reproduction is therefore not established. |

For clarity, the rebuilt/pinned **embedded wheel RECORD** SHA-256s were: base A/B/pinned `db6239c41b62b1f8f88b26160c4ba12a88c02f6d0f7f5b2d22a417be5c495845`; CTP A `540dd03b6c50aa88a793a2e257cbf3f687736e090504d2ce30621cef98b24a57`; CTP B `8a5e68450f62d1b851f7c6e97a965836a8525601448cf948bf2560ec7620f108`; CTP pinned `c44efa0370f246ebaf329a5f4a8f6624c6ad7545970ee90cfa902da166413236`. These are embedded wheel records, not installed `RECORD` hashes. No fresh install was run because the CTP wheel did not reproduce the code-pinned artifact; no installed-origin or current installed-RECORD claim is made.

## Isolation limits and guard results

The build scripts disabled pip indexes, dependency installation and caches, and used an audit hook to reject SDK/native imports and socket operations. No SDK/native import, `socket.connect`, or `getaddrinfo` event was logged. Six `socket.bind` attempts per build were denied; their caller purpose was not identified. This records blocked local bind attempts rather than asserting that no attempt occurred.

The builder venv at `D:\c41sdkf_audit\install-venv` had `include-system-site-packages = true`; `wheel 0.43.0` resolved from `C:\anaconda3\Lib\site-packages`, and pip emitted a global Anaconda `fonttools` egg deprecation warning. Thus the source/build roots were isolated and pip was offline, but the packaging tool environment was not hermetic. Tool environment provenance is an additional blocker for an acceptance-grade reproducibility result.

## Decision and minimum next evidence

The base source and all source member contents are provenance-consistent with the declared commits. The base rebuilt payload is identical to the pin, with a diagnostic exact-SHA match only after reusing the pin's ZIP timestamps. The CTP version/source identity is consistent after line-ending normalization, but the exact pinned CTP artifact was not reproduced: line-ending bytes, native PE timestamp/build bytes, ZIP timestamps, and build-environment hermeticity remain unproven. This does not close the three-artifact install chain and is not G4 acceptance.

Minimum evidence to continue without changing pins: preserve a truly isolated offline build environment with hashed Python/build-tool inputs; define and freeze the source EOL and ZIP timestamp rules; record MSVC/link flags and a reproducible native build (including the PE/debug metadata bytes); build twice in distinct roots and require exact pinned wheel hashes. Then install the exact artifacts in two fresh no-system-site venvs and verify wheel hash, embedded and installed `RECORD` separately, package origin, dependency check, and guarded non-loading of `_ctp`. If exact pinned CTP bytes cannot be reproduced, a new artifact/pin proposal requires separate review; this QA did not update it.
