# Archive count erratum — G6-S TD settlement consumer review

This addendum corrects the coordinator message's ZIP member count. The frozen
raw archive was not rewritten.

- Raw ZIP: `ctp-g6s-main-td-settlement-independent-review-2026-09-27.raw.zip`
- Raw ZIP SHA-256: `9696C1195C2C5186CD46AB685D111B542F572A5612EB281B66E1D5A4677F1172`
- `ZipFile.namelist()` regular-file members: **131**
- `ZipFile.testzip()`: **None** (no corrupt ZIP member detected)
- `SHA256SUMS.txt` entries: **130**
- Difference: the manifest lists the 130 payload/report files; the remaining
  member is the manifest itself at
  `ctp-g6s-main-td-settlement-independent-review-2026-09-27/SHA256SUMS.txt`, which is not self-hashed.

All 130 listed hashes were independently recomputed from the archive members.
The earlier phrase “130 ZIP file members” should read “130 checksum-listed
members, plus the unlisted `SHA256SUMS.txt` member.”
