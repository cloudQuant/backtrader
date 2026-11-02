import hashlib
import importlib.metadata
import json
import re
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1]).resolve()
site = root / "Lib" / "site-packages"
wheel_specs = (
    (Path(sys.argv[2]), ("backtrader", "backtrader_runtime")),
    (Path(sys.argv[3]), ("bt_api_base",)),
    (Path(sys.argv[4]), ("bt_api_ctp",)),
)
payload_counts = {}
for wheel_path, package_roots in wheel_specs:
    expected = {}
    with zipfile.ZipFile(wheel_path) as wheel:
        for name in wheel.namelist():
            if name.endswith("/"):
                continue
            top = PurePosixPath(name).parts[0]
            if top in package_roots:
                expected[name] = hashlib.sha256(wheel.read(name)).hexdigest()
    if not expected:
        raise SystemExit(f"wheel has no package payload: {wheel_path.name}")
    actual = set()
    for package in package_roots:
        package_dir = site / package
        if package_dir.exists():
            for path in package_dir.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    actual.add(path.relative_to(site).as_posix())
    if actual != set(expected):
        raise SystemExit(f"installed payload path set differs for {wheel_path.name}: missing={sorted(set(expected)-actual)[:5]} extra={sorted(actual-set(expected))[:5]}")
    for name, expected_sha in expected.items():
        installed = site.joinpath(*PurePosixPath(name).parts)
        actual_sha = hashlib.sha256(installed.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise SystemExit(f"installed payload differs from wheel: {name}")
    payload_counts[wheel_path.name] = len(expected)

sdk_artifact_pins = {}
for distribution_name, module_name, expected_version, wheel_path, expected_wheel_sha256 in (
    (
        "bt_api_base",
        "bt_api_base",
        "0.15.8",
        Path(sys.argv[3]),
        "b579a73531281d74f6e1630d447717b9f87e38bf507d82178d9ad46745017f39",
    ),
    (
        "bt_api_ctp",
        "bt_api_ctp",
        "2.0.4+iteration41.i9",
        Path(sys.argv[4]),
        "b72a48d09c80420ffdaaa7eadb51a135287ac4313caaa235d749e3b39b52796f",
    ),
):
    distribution = importlib.metadata.distribution(distribution_name)
    normalize_name = lambda value: re.sub(r"[-_.]+", "-", value).lower()
    if normalize_name(distribution.metadata.get("Name", "")) != normalize_name(distribution_name):
        raise SystemExit(f"installed distribution name mismatch: {distribution_name}")
    if distribution.version != expected_version:
        raise SystemExit(f"installed distribution version mismatch: {distribution_name}")
    entries = tuple(distribution.files or ())
    record_entries = tuple(
        entry for entry in entries
        if PurePosixPath(str(entry)).name == "RECORD"
        and any(part.endswith(".dist-info") for part in PurePosixPath(str(entry)).parts[:-1])
    )
    if len(record_entries) != 1:
        raise SystemExit(f"installed RECORD path is ambiguous: {distribution_name}")
    record_path = Path(distribution.locate_file(record_entries[0])).resolve()
    record_path.relative_to(root)
    wheel_sha256 = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    if wheel_sha256 != expected_wheel_sha256:
        raise SystemExit(f"pinned SDK wheel hash mismatch: {wheel_path.name}")
    sdk_artifact_pins[distribution_name] = {
        "distribution": distribution_name,
        "module": module_name,
        "version": distribution.version,
        "wheel_filename": wheel_path.name,
        "wheel_sha256": wheel_sha256,
        "record_sha256": hashlib.sha256(record_path.read_bytes()).hexdigest(),
    }
Path(sys.argv[5]).write_text(
    json.dumps(sdk_artifact_pins, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)

import backtrader.feeds.futures_expected_calendar as calendar
from backtrader.feeds.futures_main_contract import ProductKey

Path(calendar.__file__).resolve().relative_to(root)
retrieved = calendar.RULE_REVIEW_RETRIEVED_AT_UTC
expected_retrieved = datetime(2026, 10, 26, 15, 23, 19, tzinfo=timezone.utc)
if retrieved != expected_retrieved or calendar.RULE_REVIEW_VERSION != "public-rule-review-2026-10-26":
    raise SystemExit("installed calendar review constant mismatch")
products = tuple(ProductKey(*item) for item in (
    ("CFFEX", "IF"), ("CZCE", "SR"), ("DCE", "M"),
    ("GFEX", "LC"), ("INE", "SC"), ("SHFE", "CU"),
))
result = calendar.build_expected_daytime_calendars(
    products,
    {product.exchange_id: date(2026, 10, 26) for product in products},
    as_of=retrieved + timedelta(seconds=1),
    retrieved_at=retrieved,
)
if result.target_products != products or result.retrieved_at != retrieved:
    raise SystemExit("installed calendar caller-shaped construction mismatch")
digest = result.rules_manifest_sha256
if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
    raise SystemExit("installed calendar manifest digest invalid")
if result.evidence_mode != "expected_rule_derived":
    raise SystemExit("installed calendar evidence mode mismatch")
later = calendar.build_expected_daytime_calendars(
    products,
    {product.exchange_id: date(2026, 10, 26) for product in products},
    as_of=retrieved + timedelta(seconds=3),
    retrieved_at=retrieved + timedelta(seconds=1),
)
if later.rules_manifest_sha256 != digest:
    raise SystemExit("retrieval timestamp changed the rules manifest")
for exchange in ("DCE", "CZCE", "CFFEX"):
    notice = calendar.EXCHANGE_ANNUAL_NOTICE_METADATA[exchange]
    source_calendar = result.session_calendar_by_exchange[exchange]
    source = source_calendar.source_index[source_calendar.calendar_source_id]
    if source.version != calendar.RULE_REVIEW_VERSION:
        raise SystemExit(f"source version mismatch: {exchange}")
    if source.available_at != retrieved or source.retrieved_at != retrieved:
        raise SystemExit(f"source retrieval metadata mismatch: {exchange}")
    if not set(notice["source_urls"]).issubset(source.source_urls):
        raise SystemExit(f"issuer notice source URLs missing: {exchange}")
    if calendar.STATE_COUNCIL_HOLIDAY_REPRODUCTION_URL not in source.source_urls:
        raise SystemExit(f"holiday reproduction URL missing: {exchange}")
    if "sha256" in source.to_dict():
        raise SystemExit(f"unsupported byte hash claim present: {exchange}")
print(json.dumps({"status": "PASS", "wheel_payload_files": payload_counts,
                  "calendar_module": str(Path(calendar.__file__).resolve()),
                  "calendar_rule_version": calendar.RULE_REVIEW_VERSION,
                  "calendar_retrieved_at": retrieved.isoformat(),
                  "rules_manifest_sha256": digest,
                  "sdk_artifact_pins": sdk_artifact_pins}, sort_keys=True))