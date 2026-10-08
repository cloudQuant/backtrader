# V18 Root driver R1 actual entry diagnostic

Root executed the independently reviewed, pinned R1 driver once in the fixed isolated CPython host. It returned `BLOCKED / held_source_map_keys` before wrapper, account, native, or provider invocation. CUv2 yielded the 29 public source rows plus the two software rows; the driver compared that map to only the 29 public rows.

Root retained the original same-call lease and verified the exact 31-row union, all held byte hashes, all physical pins, and the CUv2 source pin. Root then called the original manager's normal exit, observed its postverification complete, verified physical pins again, and cleared retained references. The host session exited with code 0. No late private capture was read and no native receipt was created.

The observation contains only finite public facts from that call and its cleanup. R1 is frozen and unaccepted. The next driver version must compare the full public/software held map and exercise that actual CUv2 shape in its source/fake tests. This diagnostic establishes no formal C01 PASS; official C01 remains 0 PASS. Nothing from this failed round was staged or committed.
