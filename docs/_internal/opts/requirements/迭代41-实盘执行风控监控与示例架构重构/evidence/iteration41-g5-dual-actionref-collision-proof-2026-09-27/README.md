# G5 dual ActionRef collision proof — independent fake-only QA

**Status:** `STRUCTURAL_COLLISION_REPRODUCED / FAKE_ONLY_LOCAL_REPRO / G5 NOT_ACCEPTED / NO_WRITE / LIVE_NO_GO`.

The frozen fake-only candidate and independent QA both reproduced the same synthetic account and in-memory SQLite database receiving `native_action_ref = 1` from the G5 identity authority and `1` independently from the V21 Store allocator. Each reproduced twice under CPython 3.12.10 with byte-identical output. This is a structural collision between separate allocators, not evidence of a duplicate sent to, accepted by, or observed at a provider.

## Scope and limits

The probe exercises the V21 Store order-identity API, the G5 identity authority, and V21's internal `_allocate_ctp_native_action_ref` primitive, using synthetic identifiers and caller-supplied zero watermarks. It does **not** stage a complete V21 cancel command or create an `ctp_native_action_ref_allocations` mapping row; it does not prove the full cancellation path or a provider-side duplicate. Both durable counters can independently issue the same number because they are separate tables without shared allocation/uniqueness authority. This is a blocker to one account-wide ActionRef allocator, not G5 acceptance.

Independent QA verified the frozen candidate hashes and independently reran the script twice; both results matched the candidate captures. The receipt records zero SDK/native import attempts, network attempts, private-config reads, or provider sends. See [independent QA report](independent-qa/REPORT.md) and [machine-readable receipt](independent-qa/independent-qa-result.json), SHA-256 `F38DA0A2364BA0967BDBC94E4381D7D499B009EA68EE18F86A1F27DB2C337BE5`.

No source, SDK, native binding, provider, network, private configuration, credentials, account, or real order was used or changed. `G5 NOT_ACCEPTED / NO_WRITE / LIVE_NO_GO` remains.

## Frozen source identities

- V21 manifest SHA-256: `B3A614D62B2A4CF1B0DBDFEFEE463015157DEE38BF4C9C5119C64EF2D71D6D24`.
- V21 Store source SHA-256: `1F01EDA8466873B90359C25AAD2B61CB378D7A9FEB477FA8EC77A97FB2478E6A`.
- V21 worker SHA-256: `5E378EE77AD5C6E640AD2ECA0DACF154849E6FCFE0D04D73E9DA6EB2554087B3`.
- V21 facade SHA-256: `5B0F4086D2E900823B93ABB4E7887EA2CA2523DC62591846EA53EE4458BA438A`.
- V21 contracts SHA-256: `4CEE90AE9C8B414877E7A7B917AF85D518D45E6074418DC5B0F4BC713FAD8219`.
- G5 identity authority SHA-256: `8E7ABDD2819F66B6EC3D5FF1D5A049FCBB91AE8E71327665EE925098D35F647D`.
- Reproduction script SHA-256: `23033D685FF63B4D28F9FA9E3C306F9018B7424A0299F9F7EE7E7F9714315659`.

## Archived artifacts

The seven author files were copied byte-for-byte; each source and copy SHA/size is recorded in [COPY-RECEIPT.json](COPY-RECEIPT.json), SHA-256 `B450F41D490BDEA95DA68EC27005C85F1362F7C10D404F57C43DA4999BD94E77`. The seven-member author packet ZIP passed CRC validation and has SHA-256 `0652BE6E0D6F1CA613FEE64C3992C47E3767A3DF17CD7961F95D041B82D43084`.

Independent QA files are copied byte-for-byte under [independent-qa/](independent-qa/); the copy receipt SHA-256 is `0178806AC892F790D6FB701F1BEF37BF48E8188CA51C7E0EE04C4D5E638F1CB7`. The seven-member independent QA packet passed CRC validation and has SHA-256 `E33C29B928ACBAB226CD8676B95156192A20A360015C251271D8DE3CA296B52D`.

- [Author report](author/REPORT.md), SHA-256 `7EF2FE1099567431FBEE07B1858A2B8F887C7F55298BF078020B6ECBB236C2CB`.
- [Reproduction script](author/repro_actionref_collision.py), SHA-256 `23033D685FF63B4D28F9FA9E3C306F9018B7424A0299F9F7EE7E7F9714315659`.
- [First run output](author/run-output.json) and [second run output](author/run-output-second.json), each SHA-256 `3398221E80066083124D57EA86AF38E2D2B606DA24F2330564D2232727808AC7`.
- [SQLite schemas](author/sqlite-schema.json), SHA-256 `B84B7A60F218D8B6B529BB0F57B662C9C4A253D6B0DB93FF606236D74EFBE16F`.
- [Source hash record](author/source-hashes.json), SHA-256 `55E4FFCB4F622E56A299A9D25C5584FBEE816A2C1228C4620A183CE4ADF40EE3`.
