import csv, hashlib, json, pathlib, struct, sys, zlib
root = pathlib.Path(sys.argv[1])
runs = [
    ("025_factor_single", "default", "cases/test_copied_leaf_runs_or_fails0/backtest__025_factor_single/output/copy-default"),
    ("025_factor_single", "no-charts", "cases/test_copied_leaf_runs_or_fails1/backtest__025_factor_single/output/copy-no-charts"),
    ("026_factor_multi", "default", "cases/test_copied_leaf_runs_or_fails2/backtest__026_factor_multi/output/copy-default"),
    ("026_factor_multi", "no-charts", "cases/test_copied_leaf_runs_or_fails3/backtest__026_factor_multi/output/copy-no-charts"),
]
def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
def decode_png(path):
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"bad PNG signature: {path}")
    pos = 8
    idat = bytearray()
    width = height = bit_depth = color_type = interlace = None
    seen_iend = False
    while pos < len(raw):
        if pos + 12 > len(raw):
            raise ValueError(f"truncated PNG chunk: {path}")
        length = struct.unpack(">I", raw[pos:pos+4])[0]
        kind = raw[pos+4:pos+8]
        end = pos + 8 + length
        if end + 4 > len(raw):
            raise ValueError(f"truncated PNG payload: {path}")
        payload = raw[pos+8:end]
        expected_crc = struct.unpack(">I", raw[end:end+4])[0]
        actual_crc = zlib.crc32(kind + payload) & 0xffffffff
        if expected_crc != actual_crc:
            raise ValueError(f"PNG CRC mismatch: {path}:{kind!r}")
        if kind == b"IHDR":
            if length != 13:
                raise ValueError(f"invalid IHDR length: {path}")
            width, height, bit_depth, color_type, compression, filt, interlace = struct.unpack(">IIBBBBB", payload)
            if compression != 0 or filt != 0 or interlace not in (0, 1):
                raise ValueError(f"unsupported PNG header: {path}")
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            seen_iend = True
            if length != 0:
                raise ValueError(f"invalid IEND: {path}")
            pos = end + 4
            break
        pos = end + 4
    if not seen_iend or pos != len(raw) or width is None or not idat:
        raise ValueError(f"incomplete PNG: {path}")
    pixels = zlib.decompress(bytes(idat))
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise ValueError(f"unsupported PNG color type {color_type}: {path}")
    row_bytes = (width * channels * bit_depth + 7) // 8
    expected = height * (row_bytes + 1)
    if len(pixels) != expected:
        raise ValueError(f"PNG decoded length mismatch {len(pixels)} != {expected}: {path}")
    filters = [pixels[y * (row_bytes + 1)] for y in range(height)]
    if any(f > 4 for f in filters):
        raise ValueError(f"invalid PNG row filter: {path}")
    return {"width": width, "height": height, "bit_depth": bit_depth, "color_type": color_type, "decoded_scanline_bytes": len(pixels), "row_filters_valid": True}
results = []
for example, mode, relative in runs:
    out = root / relative
    rm = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    em_path = out / "evaluation" / "manifest.json"
    em = json.loads(em_path.read_text(encoding="utf-8"))
    dm_path = out / "dataset" / "manifest.json"
    dm = json.loads(dm_path.read_text(encoding="utf-8"))
    if rm["status"] != "COMPLETED" or rm["exit_code"] != 0:
        raise AssertionError(f"run not successful: {relative}: {rm.get('status')}/{rm.get('exit_code')}")
    if rm["broker"].get("submit") != 0 or rm["broker"].get("cancel") != 0:
        raise AssertionError(f"nonzero orders: {relative}: {rm['broker']}")
    if rm["dataset"]["dataset_id"] != em["dataset_id"] or rm["dataset"]["dataset_id"] != dm.get("dataset_id"):
        raise AssertionError(f"dataset ID mismatch: {relative}")
    if rm["evaluation_id"] != em["evaluation_id"]:
        raise AssertionError(f"evaluation ID mismatch: {relative}")
    artifact_files = []
    csv_rows = {}
    for name, meta in em["files"].items():
        path = out / "evaluation" / name
        if not path.is_file():
            raise AssertionError(f"missing evaluation artifact: {path}")
        actual_bytes = path.stat().st_size
        actual_hash = sha(path)
        if actual_bytes != meta["bytes"] or actual_hash != meta["sha256"]:
            raise AssertionError(f"evaluation artifact pin mismatch: {path}")
        item = {"name": name, "bytes": actual_bytes, "sha256": actual_hash}
        if name.lower().endswith(".csv"):
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                rows = sum(1 for _ in reader)
            data_rows = max(0, rows - 1)
            if data_rows != meta["rows"]:
                raise AssertionError(f"CSV row mismatch {path}: {data_rows} != {meta['rows']}")
            item["rows"] = data_rows
            item["rows_verified"] = True
            csv_rows[path.stem] = data_rows
        elif "rows" in meta:
            item["rows"] = meta["rows"]
            item["rows_source"] = "evaluation manifest; paired CSV rows verified"
        artifact_files.append(item)
    charts = []
    for name in em.get("charts", []):
        path = out / "evaluation" / name
        if not path.is_file():
            raise AssertionError(f"missing declared chart: {path}")
        chart_meta = decode_png(path)
        charts.append({"name": name, "bytes": path.stat().st_size, "sha256": sha(path), "decode": chart_meta})
    if not rm["charts_requested"] and charts:
        raise AssertionError(f"charts generated when disabled: {relative}")
    results.append({
        "example_id": example,
        "mode": mode,
        "output_dir": str(out),
        "run_status": rm["status"],
        "run_exit_code": rm["exit_code"],
        "evaluation_status": rm["evaluation_status"],
        "acceptance_status": rm["acceptance_status"],
        "charts_requested": rm["charts_requested"],
        "dataset_id": rm["dataset"]["dataset_id"],
        "evaluation_id": rm["evaluation_id"],
        "broker": rm["broker"],
        "versions": rm["versions"],
        "generator_version": rm["generator_version"],
        "fincore_algorithm_revision": em["fincore_algorithm_revision"],
        "result_schema_version": em["result_schema_version"],
        "export_schema_version": em["export_schema_version"],
        "dataset_manifest_sha256": sha(dm_path),
        "evaluation_manifest_sha256": sha(em_path),
        "evaluation_tables": artifact_files,
        "csv_data_rows": csv_rows,
        "charts": charts,
        "required_output_validation": rm["required_output_validation"],
    })
summary = {
    "schema": "iteration45-installed-copy-factor-artifact-summary-v1",
    "scope": "read-only installed-wheel copied-example outputs; no account/network access; audit script imports standard library only",
    "repository_head": "7916441772cb8c33b96e46eeaabdc6efaa5e1cd0",
    "backtrader_wheel_source_commit": "cf6a40e0db722e501fc109306624580f2f7e1642",
    "backtrader_wheel_sha256": "57ef4f2b6f71cd63558db29020dfceaf5630693ba5f626ae034d7acf92bb47f6",
    "fincore_wheel_source_commit": "d7",
    "fincore_wheel_sha256": "fbd05395b193ee6510a97c54947c1c3d079f03ca3bd4d9677583519df783d607",
    "pytest": {"selected": 7, "passed": 7, "deselected": 66, "exit_code": 0, "duration_seconds": 1272.99, "warning": "PytestConfigWarning: asyncio_default_fixture_loop_scope is unknown because -p no:asyncio is required"},
    "runs": results,
}
path = root / "artifact-summary.json"
path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({"summary_path": str(path), "runs": len(results), "all_checks_passed": True, "tables_per_run": [len(r["evaluation_tables"]) for r in results], "pngs_per_run": [len(r["charts"]) for r in results]}, indent=2))


