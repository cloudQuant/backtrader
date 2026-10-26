[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = 'D:\source_code\backtrader'
$commit = 'ae218c04ca521aaad3ef8c6aa38f17f6c334444d'
$out = 'D:\temp\i51cal-consumer-20261027-r1'
$py = 'C:\anaconda3\python.exe'
$taskkill = Join-Path $env:WINDIR 'System32\taskkill.exe'
$r2 = 'D:\temp\ac51-r0-sdk-20261026-r2'
$oldHouse = Join-Path $r2 'offline-wheelhouse'
$inventoryPath = Join-Path $repo '.codex-tmp\r0_dependency_inventory_20261025.json'
$sourceVerifier = 'D:\temp\ac51-r0-sdk-20261026-bt-wheelprep\verify_wheel_python_payload.py'
$consumerVerifier = Join-Path $r2 'verify_consumer.py'

function Assert-That([bool] $ok, [string] $message) {
    if (-not $ok) { throw $message }
}

function Get-Sha256([string] $path) {
    (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Pin-File([string] $path, [string] $sha, [long] $size) {
    Assert-That (Test-Path -LiteralPath $path -PathType Leaf) "Missing file: $path"
    $item = Get-Item -LiteralPath $path
    $actualSha = Get-Sha256 $path
    Assert-That ($actualSha -eq $sha.ToLowerInvariant()) "SHA-256 mismatch: $path"
    Assert-That ([long]$item.Length -eq $size) "Size mismatch: $path"
    [ordered]@{ path = $path; size_bytes = [long]$item.Length; sha256 = $actualSha }
}

function Save-Manifest {
    [IO.File]::WriteAllText(
        $manifestPath,
        ((ConvertTo-Json -InputObject $manifest -Depth 12) + "`r`n"),
        [Text.UTF8Encoding]::new($false)
    )
}

function Run-Child([string] $phase, [string] $file, [string[]] $arguments, [int] $timeoutSeconds) {
    $stdout = Join-Path $out "$phase.stdout.log"
    $stderr = Join-Path $out "$phase.stderr.log"
    $started = [DateTimeOffset]::UtcNow
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $record = [ordered]@{
        phase = $phase; executable = $file; arguments = @($arguments)
        timeout_seconds = $timeoutSeconds; started_utc = $started.ToString('o')
        stdout = $stdout; stderr = $stderr; exit_code = $null
        timed_out = $false; duration_seconds = $null
    }
    try {
        $process = Start-Process -FilePath $file -ArgumentList $arguments `
            -WorkingDirectory $out -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr -PassThru -WindowStyle Hidden
        if (-not $process.WaitForExit($timeoutSeconds * 1000)) {
            $record.timed_out = $true
            if (-not $process.HasExited) {
                & $taskkill /PID $process.Id /T /F 2>&1 |
                    Out-File -LiteralPath (Join-Path $out "$phase-timeout-taskkill.log") -Encoding utf8
                [void]$process.WaitForExit(10000)
            }
            throw "$phase timed out after $timeoutSeconds seconds; process tree stopped and outputs preserved."
        }
        $process.WaitForExit()
        $process.Refresh()
        $record.exit_code = [int]$process.ExitCode
        if ($record.exit_code -ne 0) { throw "$phase exited $($record.exit_code)." }
    }
    catch {
        $timer.Stop()
        $record.duration_seconds = [Math]::Round($timer.Elapsed.TotalSeconds, 3)
        $record.ended_utc = [DateTimeOffset]::UtcNow.ToString('o')
        $manifest.commands = @($manifest.commands) + @($record)
        Save-Manifest
        throw
    }
    $timer.Stop()
    $record.duration_seconds = [Math]::Round($timer.Elapsed.TotalSeconds, 3)
    $record.ended_utc = [DateTimeOffset]::UtcNow.ToString('o')
    $manifest.commands = @($manifest.commands) + @($record)
    Save-Manifest
}

Assert-That (-not (Test-Path -LiteralPath $out)) "Output already exists; preserve it and stop: $out"
Assert-That (Test-Path -LiteralPath $py -PathType Leaf) "Missing Python interpreter: $py"
Assert-That (Test-Path -LiteralPath $oldHouse -PathType Container) "Missing accepted offline wheelhouse: $oldHouse"
Assert-That (Test-Path -LiteralPath $inventoryPath -PathType Leaf) "Missing public dependency pin inventory: $inventoryPath"
Assert-That (Test-Path -LiteralPath $sourceVerifier -PathType Leaf) "Missing accepted Python-payload verifier: $sourceVerifier"
Assert-That (Test-Path -LiteralPath $consumerVerifier -PathType Leaf) "Missing accepted consumer verifier: $consumerVerifier"
New-Item -ItemType Directory -Path $out | Out-Null
$manifestPath = Join-Path $out 'run-manifest.json'
$sdkPinFile = Join-Path $out 'ctp-sdk-artifact-pins.json'
$manifest = [ordered]@{
    schema_version = 1
    status = 'RUNNING'
    phase = 'preflight'
    evidence_level = 'LOCAL_INSTALLED_CALENDAR_CONSUMER_ONLY'
    formal_account_acceptance_claimed = $false
    repository = $repo
    branch = 'dev'
    source_commit = $commit
    source_parent = 'a995a23654d9f87d7ab87bba897e25b61d4896f2'
    output_root = $out
    reused_ctp_wheel = $true
    ctp_rebuilt = $false
    accepted_matrix_rerun = $false
    commands = @()
    phases = [ordered]@{}
    pins = [ordered]@{}
}
Save-Manifest

try {
    $git = (Get-Command git.exe -ErrorAction Stop | Select-Object -First 1 -ExpandProperty Source)
    $preflightLog = Join-Path $out 'dev-ancestor.stdout.log'
    $preflightErr = Join-Path $out 'dev-ancestor.stderr.log'
    $preflightTimer = [Diagnostics.Stopwatch]::StartNew()
    $resolved = (& $git -C $repo rev-parse "$commit^{commit}" 2> $preflightErr | Out-String).Trim()
    $resolvedExit = $LASTEXITCODE
    if ($resolvedExit -ne 0 -or $resolved -ne $commit) { throw 'Accepted source commit cannot be resolved exactly.' }
    & $git -C $repo merge-base --is-ancestor $commit refs/heads/dev 1> $preflightLog 2>> $preflightErr
    $ancestorExit = $LASTEXITCODE
    $preflightTimer.Stop()
    if ($ancestorExit -ne 0) { throw 'Accepted calendar commit is not reachable from dev.' }
    $manifest.phases.source_preflight = [ordered]@{
        status = 'PASS'; resolved_commit = $resolved; dev_ancestor_exit = $ancestorExit
        duration_seconds = [Math]::Round($preflightTimer.Elapsed.TotalSeconds, 3)
        stdout = $preflightLog; stderr = $preflightErr
    }
    Save-Manifest

    $archive = Join-Path $out 'source.zip'
    Run-Child 'git-archive' $git @('-C', $repo, 'archive', '--format=zip', "--output=$archive", $commit,
        'setup.py', 'pyproject.toml', 'README.md', 'LICENSE', 'backtrader', 'backtrader_runtime') 120
    $archiveSha = Get-Sha256 $archive
    $manifest.pins.source_archive = [ordered]@{
        path = $archive; size_bytes = [long](Get-Item -LiteralPath $archive).Length; sha256 = $archiveSha
    }
    $source = Join-Path $out 'source'
    $phaseTimer = [Diagnostics.Stopwatch]::StartNew()
    Expand-Archive -LiteralPath $archive -DestinationPath $source
    $phaseTimer.Stop()
    $manifest.phases.archive_extract = [ordered]@{
        status = 'PASS'; source_root = $source; duration_seconds = [Math]::Round($phaseTimer.Elapsed.TotalSeconds, 3)
    }
    Save-Manifest

    $wheelDir = Join-Path $out 'wheel'
    New-Item -ItemType Directory -Path $wheelDir | Out-Null
    $env:PYTHONPATH = ''
    $env:PYTHONHOME = ''
    $env:PYTHONNOUSERSITE = '1'
    $env:PIP_CONFIG_FILE = 'NUL'
    $env:PIP_NO_INDEX = ''
    $env:PIP_EXTRA_INDEX_URL = ''
    $env:PIP_FIND_LINKS = ''
    Run-Child 'backtrader-wheel-build' $py @('-I', '-m', 'pip', 'wheel', '--disable-pip-version-check',
        '--no-cache-dir', '--no-deps', '--index-url', 'https://pypi.org/simple', '--wheel-dir', $wheelDir, $source) 900
    $wheelMatches = @(Get-ChildItem -LiteralPath $wheelDir -File -Filter 'back_trader_python-1.4.0-*.whl')
    Assert-That ($wheelMatches.Count -eq 1) 'Expected exactly one Backtrader 1.4.0 wheel.'
    $btWheel = $wheelMatches[0].FullName
    $manifest.pins.backtrader_wheel = [ordered]@{
        path = $btWheel; size_bytes = [long]$wheelMatches[0].Length; sha256 = Get-Sha256 $btWheel
    }
    $payloadCheck = Join-Path $out 'verify_wheel_python_payload.py'
    Copy-Item -LiteralPath $sourceVerifier -Destination $payloadCheck
    $payloadSource = [IO.File]::ReadAllText($payloadCheck)
    $oldCommitLiteral = "'source_commit': '3eacbd197ed4812c2e0627d2f994065934d6f978'"
    Assert-That ($payloadSource.Contains($oldCommitLiteral)) 'Payload verifier source-commit literal changed; review before use.'
    $payloadSource = $payloadSource.Replace($oldCommitLiteral, "'source_commit': '$commit'")
    [IO.File]::WriteAllText($payloadCheck, $payloadSource, [Text.UTF8Encoding]::new($false))
    $payloadResult = Join-Path $out 'wheel-python-payload-verification.json'
    Run-Child 'source-to-wheel-python-payload' $py @('-I', $payloadCheck, $source, $btWheel, $payloadResult, $archiveSha) 120
    $payloadObservation = Get-Content -LiteralPath $payloadResult -Raw | ConvertFrom-Json
    Assert-That ($payloadObservation.status -eq 'PASS') 'Source-to-wheel Python payload comparison did not pass.'
    Assert-That (@($payloadObservation.missing_from_wheel).Count -eq 0 -and
        @($payloadObservation.extra_in_wheel).Count -eq 0 -and @($payloadObservation.hash_mismatches).Count -eq 0) `
        'Source-to-wheel Python payload paths or hashes differ.'
    $manifest.phases.source_to_wheel_payload = [ordered]@{ status = 'PASS'; result = $payloadResult; observation = $payloadObservation }
    Save-Manifest

    $offline = Join-Path $out 'offline-wheelhouse'
    New-Item -ItemType Directory -Path $offline | Out-Null
    $oldBtName = 'back_trader_python-1.4.0-py3-none-any.whl'
    $sourceWheelFiles = @(Get-ChildItem -LiteralPath $oldHouse -File -Filter '*.whl')
    Assert-That ($sourceWheelFiles.Count -eq 52) 'Accepted R2 offline wheelhouse no longer has 52 wheels.'
    $oldBt = @(Get-ChildItem -LiteralPath $oldHouse -File -Filter $oldBtName)
    Assert-That ($oldBt.Count -eq 1 -and (Get-Sha256 $oldBt[0].FullName) -eq
        'd342740a961a420f5a081e0f74563fe6e0e333f818d398c60d73a691986dc4dc') 'Prior Backtrader wheel pin differs from the excluded artifact.'
    foreach ($item in $sourceWheelFiles) {
        if ($item.Name -ne $oldBtName) { Copy-Item -LiteralPath $item.FullName -Destination $offline }
    }
    $btOffline = Join-Path $offline $oldBtName
    Copy-Item -LiteralPath $btWheel -Destination $btOffline
    $btOfflinePin = Pin-File $btOffline $manifest.pins.backtrader_wheel.sha256 $manifest.pins.backtrader_wheel.size_bytes

    $inventory = Get-Content -LiteralPath $inventoryPath -Raw | ConvertFrom-Json
    Assert-That ([int]$inventory.download_exit_code -eq 0) 'Accepted dependency inventory download was not successful.'
    $dependencyPins = @($inventory.wheels | Where-Object { $_.name -notin @('back-trader-python', 'bt_api_base') })
    Assert-That ($dependencyPins.Count -eq 49) 'Expected exactly 49 previously pinned dependency wheels.'
    foreach ($item in $dependencyPins) {
        $path = Join-Path $offline ([string]$item.filename)
        $pin = Pin-File $path ([string]$item.sha256) ([long]$item.size_bytes)
        $manifest.pins[$item.filename] = $pin
    }
    $accepted = Get-Content -LiteralPath (Join-Path $r2 'run-manifest.json') -Raw | ConvertFrom-Json
    $baseOffline = Join-Path $offline 'bt_api_base-0.15.8-py3-none-any.whl'
    $ctpOffline = Join-Path $offline 'bt_api_ctp-2.0.4+iteration41.i9-cp311-cp311-win_amd64.whl'
    $basePin = Pin-File $baseOffline $accepted.base_wheel.sha256 ([long]$accepted.base_wheel.size_bytes)
    $ctpPin = Pin-File $ctpOffline $accepted.phases.build.ctp_wheel.sha256 ([long]$accepted.phases.build.ctp_wheel.size_bytes)
    $manifest.pins.backtrader_offline_copy = $btOfflinePin
    $manifest.pins.bt_api_base = $basePin
    $manifest.pins.bt_api_ctp = $ctpPin
    $offlineWheels = @(Get-ChildItem -LiteralPath $offline -File -Filter '*.whl')
    Assert-That ($offlineWheels.Count -eq 52) 'Curated offline wheelhouse must contain 52 wheels.'
    $manifest.phases.offline_wheelhouse = [ordered]@{
        status = 'PASS'; wheel_count = $offlineWheels.Count; old_backtrader_wheel_excluded = $oldBtName
        new_backtrader_wheel = $btOfflinePin; base = $basePin; ctp = $ctpPin; dependency_count = $dependencyPins.Count
    }
    Save-Manifest

    $consumer = Join-Path $out 'consumer'
    Run-Child 'consumer-venv-create' $py @('-I', '-m', 'venv', $consumer) 180
    $consumerPython = Join-Path $consumer 'Scripts\python.exe'
    $versionCheck = Join-Path $out 'check_consumer_python.py'
    [IO.File]::WriteAllText($versionCheck,
        "import sys`nassert sys.version_info[:3] == (3, 11, 5), sys.version`n", [Text.UTF8Encoding]::new($false))
    Run-Child 'consumer-python-version' $consumerPython @('-I', $versionCheck) 30
    $manifest.phases.consumer_venv = [ordered]@{ status = 'PASS'; root = $consumer; python = $consumerPython; version = '3.11.5' }
    Save-Manifest

    $env:PIP_NO_INDEX = '1'
    $env:PIP_CONFIG_FILE = 'NUL'
    $env:PYTHONPATH = ''
    $env:PYTHONHOME = ''
    $env:PYTHONNOUSERSITE = '1'
    Run-Child 'offline-install' $consumerPython @('-I', '-m', 'pip', 'install', '--disable-pip-version-check',
        '--no-cache-dir', '--only-binary=:all:', '--no-index', '--find-links', $offline,
        $btOffline, $baseOffline, $ctpOffline) 900
    $manifest.phases.install = [ordered]@{ status = 'PASS'; offline = $true; explicit_roots = @($btOfflinePin, $basePin, $ctpPin) }
    Save-Manifest

    Run-Child 'consumer-pip-check' $consumerPython @('-I', '-m', 'pip', 'check') 120
    $verifyConsumer = Join-Path $out 'verify_consumer.py'
    Copy-Item -LiteralPath $consumerVerifier -Destination $verifyConsumer
    Run-Child 'consumer-record-origin-native' $consumerPython @('-I', $verifyConsumer, $consumer) 120
    $consumerObservation = Get-Content -LiteralPath (Join-Path $out 'consumer-record-origin-native.stdout.log') -Raw | ConvertFrom-Json
    Assert-That ($consumerObservation.status -eq 'PASS' -and $consumerObservation.ctp_native_loaded -eq $true) `
        'Installed RECORD/origin/native CTP verifier did not pass.'
    $manifest.phases.record_origin_native = [ordered]@{ status = 'PASS'; pip_check = 'PASS'; result = $consumerObservation }
    Save-Manifest

    $installedVerifier = Join-Path $out 'verify_installed_payload_calendar.py'
    $installedVerifierSource = @'
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
'@
    [IO.File]::WriteAllText($installedVerifier, $installedVerifierSource, [Text.UTF8Encoding]::new($false))
    Run-Child 'installed-payload-calendar' $consumerPython @('-I', $installedVerifier, $consumer, $btOffline, $baseOffline, $ctpOffline, $sdkPinFile) 120
    $installedObservation = Get-Content -LiteralPath (Join-Path $out 'installed-payload-calendar.stdout.log') -Raw | ConvertFrom-Json
    Assert-That ($installedObservation.status -eq 'PASS') 'Installed wheel-payload/calendar smoke did not pass.'
    $manifest.pins.sdk_artifact_pins = $installedObservation.sdk_artifact_pins
    $manifest.pins.sdk_artifact_pins_file = [ordered]@{
        path = $sdkPinFile; size_bytes = [long](Get-Item -LiteralPath $sdkPinFile).Length; sha256 = Get-Sha256 $sdkPinFile
    }
    $manifest.phases.installed_payload_calendar = [ordered]@{ status = 'PASS'; result = $installedObservation }
    $manifest.phase = 'complete'
    $manifest.status = 'PASS'
    $manifest.completed_utc = [DateTimeOffset]::UtcNow.ToString('o')
    Save-Manifest
    Write-Output ("PASS: {0}" -f $manifestPath)
}
catch {
    if (Test-Path -LiteralPath $sdkPinFile -PathType Leaf) {
        $manifest.pins.sdk_artifact_pins = Get-Content -LiteralPath $sdkPinFile -Raw | ConvertFrom-Json
        $manifest.pins.sdk_artifact_pins_file = [ordered]@{
            path = $sdkPinFile; size_bytes = [long](Get-Item -LiteralPath $sdkPinFile).Length; sha256 = Get-Sha256 $sdkPinFile
        }
    }
    $manifest.status = 'FAIL'
    $manifest.phase = 'failed'
    $manifest.failure = [string]$_.Exception.Message
    $manifest.failed_utc = [DateTimeOffset]::UtcNow.ToString('o')
    Save-Manifest
    throw
}
