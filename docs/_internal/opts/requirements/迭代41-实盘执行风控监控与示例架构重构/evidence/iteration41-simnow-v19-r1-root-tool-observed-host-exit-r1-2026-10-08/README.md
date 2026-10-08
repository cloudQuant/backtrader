# SimNow V19 readonly round and Root host cleanup

Root verified the exact R2 25-file packet, three-file V17 regression support archive and independent source review. One actual readonly activation completed authentication, login and six baseline/final queries. The parent returned PASS / read_only_candidate_complete in 23.328 seconds; the typed native worker exited 0 and ended at worker_receipt/end, record 94. This accepts the current readonly repair round, including same-handle admission, consumed-marker and claim revalidation. It does not establish formal C01 or any order/cancel acceptance.

Both outer Jobs reached zero, readers joined, EOF and handles closed without forced termination. Root explicitly postverified and closed the outer physical source/runtime hold. Tool session 1311 then exited 0 with no retained references. No late private artifacts were read. Reported order/cancel counts were zero; the outer observer did not independently inspect provider sends.

The source-fake suite independently passed 8 tests and covers the old V17 EOF defect, all three checked rewind paths, failed seek, changed bytes and closure. ACL leaves in those tests are synthetic. Actual profile results and host cleanup are separate evidence. Formal SimNow C01 PASS remains zero until the same-process Root ledger/custody bridge is accepted.
