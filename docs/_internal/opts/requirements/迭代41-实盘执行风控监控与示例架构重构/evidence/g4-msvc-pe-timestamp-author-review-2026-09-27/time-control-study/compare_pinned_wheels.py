import hashlib, json, os, struct, sys, time, zipfile

WHEEL_MEMBER = "bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd"
WHEELS = {
    "pin": (r"D:\c41sdki2_audit\wheels\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl", "988c52a91a12d3256caadf27df2ae1f1eb45e54fc6c4f63b7abba0363f34c4ff"),
    "prior_a": (r"D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927\build-a\wheelhouse\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl", "7759a11487ddb0067e3fb755366c989b1fe55a965f3d712526d59b6bb228817d"),
    "prior_b": (r"D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927\build-b\wheelhouse\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl", "1de546d5c18b439d77d26dd0039e08b4facbbeaf1b0b865a38eafa211c2d46f8"),
    "brepro_a": (r"D:\temp\iteration41-g4-ctp-native-repro-isolated-20260927\wheelhouse-a\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl", "70efd2ee7302b0fa197e6709a044ef85d50ab1cbc36f79d9d055d81b289a2ed2"),
    "brepro_b": (r"D:\temp\iteration41-g4-ctp-native-repro-isolated-20260927\wheelhouse-b\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl", "70efd2ee7302b0fa197e6709a044ef85d50ab1cbc36f79d9d055d81b289a2ed2"),
    "strict_c": (r"D:\temp\iteration41-g4-ctp-native-repro-isolated-20260927\wheelhouse-c\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl", "7dad3140ab8a700939022282a78f75b165a612637bac90da5caa7df06f4d64f7"),
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def pe_facts(data):
    peoff = struct.unpack_from("<I", data, 0x3c)[0]
    if data[peoff:peoff+4] != b"PE\0\0":
        raise ValueError("bad PE signature")
    coff_ts = struct.unpack_from("<I", data, peoff+8)[0]
    nsec = struct.unpack_from("<H", data, peoff+6)[0]
    opt_size = struct.unpack_from("<H", data, peoff+20)[0]
    opt = peoff+24
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic != 0x20b:
        raise ValueError(f"unexpected optional magic: {magic:#x}")
    dd = opt+112
    debug_rva, debug_size = struct.unpack_from("<II", data, dd+6*8)
    sec_table = opt+opt_size
    debug_raw = None
    for i in range(nsec):
        s = sec_table+i*40
        vsize, va, rawsize, rawptr = struct.unpack_from("<IIII", data, s+8)
        if va <= debug_rva < va+max(vsize, rawsize):
            debug_raw = rawptr+(debug_rva-va)
            break
    if debug_raw is None or debug_size < 28:
        raise ValueError("debug directory RVA not mapped")
    entries = []
    for pos in range(debug_raw, debug_raw+debug_size, 28):
        typ = struct.unpack_from("<I", data, pos+12)[0]
        ts = struct.unpack_from("<I", data, pos+4)[0]
        size = struct.unpack_from("<I", data, pos+16)[0]
        ptr = struct.unpack_from("<I", data, pos+24)[0]
        entries.append({"type":typ,"timestamp":ts,"size":size,"pointer":ptr,"file_offset":pos})
    return {
        "pe_offset":peoff,
        "coff_timestamp":coff_ts,
        "coff_timestamp_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(coff_ts)),
        "optional_magic":magic,
        "debug_rva":debug_rva,
        "debug_size":debug_size,
        "debug_raw_offset":debug_raw,
        "debug_entries":entries,
    }

def get_wheel(label, item):
    path, expected = item
    with open(path, "rb") as f:
        wheel = f.read()
    actual = sha(wheel)
    if actual != expected:
        raise ValueError(f"{label}: wheel hash mismatch {actual} != {expected}")
    with zipfile.ZipFile(path, "r") as z:
        bad = z.testzip()
        if bad is not None:
            raise ValueError(f"{label}: zip CRC failed at {bad}")
        pyd = z.read(WHEEL_MEMBER)
    return {"path":path,"wheel_bytes":len(wheel),"wheel_sha256":actual,"zip_test":"passed",
            "pyd_bytes":len(pyd),"pyd_sha256":sha(pyd),"pe":pe_facts(pyd),"pyd":pyd}

artifacts = {name:get_wheel(name, item) for name,item in WHEELS.items()}
base = artifacts["pin"]
comparisons = {}
for label, art in artifacts.items():
    if label == "pin":
        continue
    left, right = base["pyd"], art["pyd"]
    diffs = [i for i,(a,b) in enumerate(zip(left,right)) if a != b]
    comparisons["pin_vs_"+label] = {
        "equal_length":len(left)==len(right),
        "diff_count_common_prefix":len(diffs),
        "diff_offsets_hex":[hex(i) for i in (diffs if len(diffs)<=100 else diffs[:16]+diffs[-16:])],"diff_offsets_truncated":len(diffs)>100,
        "coff_timestamp_bytes_pin":left[0x120:0x124].hex(),
        "coff_timestamp_bytes_other":right[0x120:0x124].hex(),
        "debug_timestamp_bytes_pin":left[0xa26c54:0xa26c58].hex(),
        "debug_timestamp_bytes_other":right[0xa26c54:0xa26c58].hex(),
    }
result = {
    "scope":"Offline standard-library zip/PE byte inspection; no wheel installation or native import/load.",
    "python":sys.version,
    "site_loaded":"site" in sys.modules,
    "member":WHEEL_MEMBER,
    "artifacts":{k:{kk:vv for kk,vv in v.items() if kk!="pyd"} for k,v in artifacts.items()},
    "comparisons":comparisons,
}
out = os.path.join(os.path.dirname(__file__), "timestamp-comparison.json")
with open(out, "w", encoding="utf-8", newline="\n") as f:
    json.dump(result, f, indent=2, sort_keys=True)
    f.write("\n")
print(json.dumps({
    "output":out,
    "site_loaded":result["site_loaded"],
    "comparisons":{k:v["diff_offsets_hex"] for k,v in comparisons.items()},
    "pyd_sha256":{k:v["pyd_sha256"] for k,v in artifacts.items()},
    "coff_timestamps":{k:hex(v["pe"]["coff_timestamp"]) for k,v in artifacts.items()},
}, indent=2))

