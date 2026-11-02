# Bounded R0 CTP wheel build and isolated consumer. Authored only; not run.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $OutputRoot,
    [Parameter(Mandatory = $true)][string] $BacktraderWheel,
    [Parameter(Mandatory = $true)][string] $BacktraderWheelSha256,
    [Parameter(Mandatory = $true)][string] $BacktraderSourceRevision,
    [ValidateRange(1, 3600)][int] $BuildTimeoutSeconds = 3600,
    [ValidateRange(1, 1800)][int] $InstallTimeoutSeconds = 900,
    [ValidateRange(1, 600)][int] $CheckTimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = 'D:\source_code\backtrader'
$archive = 'D:\temp\ac51-r0-sdk-20261025-r1'
$deps = Join-Path $archive 'dependencies'
$baseWheel = Join-Path $archive 'wheelhouse\bt_api_base-0.15.8-py3-none-any.whl'
$baseZip = Join-Path $archive 'bt_api_base.zip'
$ctpZip = Join-Path $archive 'bt_api_ctp.zip'
$identityPath = Join-Path $archive 'source-identities.json'
$inventoryPath = Join-Path $repo '.codex-tmp\r0_dependency_inventory_20261025.json'
$python311 = 'C:\anaconda3\python.exe'
$vcvars = 'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat'
$clExpected = 'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.42.34433\bin\Hostx64\x64\cl.exe'
$clVersion = '14.42.34433'
$baseCommit = 'fb47f3dd733613494aa1d86cfd94b2d6fe70314d'
$ctpCommit = '48b476ea90665791c7d2f86935720ce238931520'
$baseZipHash = '59efc739d67c17721dd4a413445a65aaa57a6ddef8309f256cb3fe89697223fb'
$ctpZipHash = 'd05e71528ae326e5e2cb1f237f7a897feef45d943ba5f5cdff24c8f602a07188'
$baseWheelHash = 'b579a73531281d74f6e1630d447717b9f87e38bf507d82178d9ad46745017f39'
$baseWheelSize = 153051
$ctpWheelName = 'bt_api_ctp-2.0.4+iteration41.i9-cp311-cp311-win_amd64.whl'
$cmd = Join-Path $env:WINDIR 'System32\cmd.exe'
$taskkill = Join-Path $env:WINDIR 'System32\taskkill.exe'

function Assert-That([bool] $ok, [string] $message) { if (-not $ok) { throw $message } }
function Hash([string] $path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Pin([string] $path, [string] $sha, [long] $size = -1) {
    Assert-That (Test-Path -LiteralPath $path -PathType Leaf) "Missing file: $path"
    $item = Get-Item -LiteralPath $path
    Assert-That ((Hash $path) -eq $sha.ToLowerInvariant()) "SHA-256 mismatch: $path"
    if ($size -ge 0) { Assert-That ([long]$item.Length -eq $size) "Size mismatch: $path" }
    [ordered]@{ path = $path; size_bytes = [long]$item.Length; sha256 = (Hash $path) }
}
function Write-Batch([string] $path, [string[]] $lines) {
    [IO.File]::WriteAllText($path, (($lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
}
function Run-Batch([string] $batch, [int] $seconds, [string] $label, [string] $root) {
    $p = New-Object Diagnostics.Process
    $p.StartInfo.FileName = $cmd
    $p.StartInfo.Arguments = "/d /c call $batch"
    $p.StartInfo.WorkingDirectory = $root
    $p.StartInfo.UseShellExecute = $false
    $p.StartInfo.CreateNoWindow = $true
    Assert-That ([bool]($p.Start())) "Could not start $label"
    if (-not $p.WaitForExit($seconds * 1000)) {
        if (-not $p.HasExited) {
            $out = & $taskkill /PID $p.Id /T /F 2>&1
            [IO.File]::WriteAllText((Join-Path $root "$label-timeout.txt"), ($out | Out-String), [Text.Encoding]::UTF8)
            [void]$p.WaitForExit(10000)
        }
        throw "$label timed out after $seconds seconds; outputs were retained."
    }
    $p.WaitForExit()
    Assert-That ($p.ExitCode -eq 0) "$label exited $($p.ExitCode); inspect its logs."
}
function Save-Manifest([string] $path, [object] $value) {
    [IO.File]::WriteAllText($path, ((ConvertTo-Json -InputObject $value -Depth 10) + "`r`n"), [Text.Encoding]::UTF8)
}

$out = [IO.Path]::GetFullPath($OutputRoot).TrimEnd('\')
Assert-That ($out -match '^(?i:D:\\temp\\[A-Za-z0-9_.-]+)$') 'OutputRoot must be a new cmd-safe directory directly under D:\temp.'
Assert-That (-not (Test-Path -LiteralPath $out)) "OutputRoot already exists; this wrapper never overwrites or cleans it: $out"
Assert-That (Test-Path -LiteralPath 'D:\temp' -PathType Container) 'D:\temp must exist.'
$memory = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
Assert-That ($null -ne $memory.FreePhysicalMemory) 'Could not read available physical memory.'
$freeMemoryBytes = [long]$memory.FreePhysicalMemory * 1024
Assert-That ($freeMemoryBytes -ge 2147483648) 'At least 2 GiB of free physical memory is required before the build/install phases.'
Assert-That ($BacktraderWheelSha256 -match '^(?i:[0-9a-f]{64})$') 'Provide the separately verified current Backtrader wheel SHA-256.'
Assert-That ($BacktraderSourceRevision -match '^(?i:[0-9a-f]{40})$') 'Provide the full current Backtrader source revision.'
$btPath = [IO.Path]::GetFullPath($BacktraderWheel)
Assert-That ($btPath -match '^(?i:D:\\temp\\[A-Za-z0-9_.\\-]+\.whl)$') 'Backtrader wheel must be a local D:\temp wheel path without cmd metacharacters.'
$btPin = Pin $btPath $BacktraderWheelSha256
Assert-That ([IO.Path]::GetFileName($btPath) -match '^back_trader_python-1\.4\.0-.*\.whl$') 'Current wheel must be Backtrader 1.4.0.'

$ids = Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
$baseArchivePin = Pin $baseZip $baseZipHash
$ctpArchivePin = Pin $ctpZip $ctpZipHash
Assert-That ($ids.bt_api_base.source_commit -eq $baseCommit -and $ids.bt_api_base.archive_sha256 -eq $baseArchivePin.sha256) 'bt_api_base archive identity mismatch.'
Assert-That ($ids.bt_api_ctp.source_commit -eq $ctpCommit -and $ids.bt_api_ctp.archive_sha256 -eq $ctpArchivePin.sha256) 'bt_api_ctp archive identity mismatch.'
$basePin = Pin $baseWheel $baseWheelHash $baseWheelSize
$inventory = Get-Content -LiteralPath $inventoryPath -Raw | ConvertFrom-Json
Assert-That ([int]$inventory.download_exit_code -eq 0) 'Dependency wheel download did not complete.'
Assert-That (([IO.Path]::GetFullPath([string]$inventory.destination).TrimEnd('\')) -ieq ([IO.Path]::GetFullPath($deps).TrimEnd('\'))) 'Dependency inventory path mismatch.'
Assert-That (@($inventory.wheels).Count -eq 51) 'Expected the pinned 51-wheel dependency inventory.'
$pins = @(); $oldBt = @(); $inventoryBase = @()
foreach ($wheel in $inventory.wheels) {
    $path = Join-Path $deps ([string]$wheel.filename)
    $pins += Pin $path ([string]$wheel.sha256) ([long]$wheel.size_bytes)
    if ($wheel.name -eq 'back-trader-python') { $oldBt += $wheel }
    if ($wheel.name -eq 'bt_api_base') { $inventoryBase += $wheel }
}
Assert-That ($oldBt.Count -eq 1 -and $oldBt[0].version -eq '1.4.0') 'Expected exactly one historical a69 Backtrader wheel in dependency inventory.'
Assert-That ($inventoryBase.Count -eq 1 -and $inventoryBase[0].sha256 -eq $baseWheelHash -and [long]$inventoryBase[0].size_bytes -eq $baseWheelSize) 'Inventory bt_api_base wheel differs from the separately pinned base wheel.'
Assert-That (Test-Path -LiteralPath $vcvars -PathType Leaf) 'Pinned VS2022 vcvarsall.bat is missing.'
Assert-That (Test-Path -LiteralPath $clExpected -PathType Leaf) 'Pinned MSVC 14.42 x64 compiler is missing.'
Assert-That (Test-Path -LiteralPath $python311 -PathType Leaf) 'Python 3.11 venv creator is missing.'

$consumer = Join-Path $out 'consumer'
$manifestPath = Join-Path $out 'run-manifest.json'
$manifest = [ordered]@{
    schema_version = 2; status = 'RUNNING'; phase = 'preflight_complete'
    evidence_level = 'LOCAL_INSTALLED_WHEEL_CONSUMER_ONLY'; formal_account_acceptance_claimed = $false
    bt_api_base_commit = $baseCommit; bt_api_ctp_commit = $ctpCommit
    backtrader_source_revision = $BacktraderSourceRevision; backtrader_wheel = $btPin
    archives = @($baseArchivePin, $ctpArchivePin); base_wheel = $basePin
    dependency_wheel_count = $pins.Count; available_memory_bytes_at_preflight = $freeMemoryBytes
    historical_a69_wheel_excluded = $oldBt[0].filename
    duplicate_base_wheel_excluded = $inventoryBase[0].filename
    dependency_inventory_stderr_characters = ([string]$inventory.stderr).Length
    consumer_root = $consumer; compiler = $clExpected; phases = [ordered]@{}
}
New-Item -ItemType Directory -Path $out | Out-Null
Save-Manifest $manifestPath $manifest
try {
    $stage = Join-Path $out 'stage'; $buildTemp = Join-Path $out 'build-temp'
    $ctpHouse = Join-Path $out 'ctp-wheelhouse'; $offline = Join-Path $out 'offline-wheelhouse'
    New-Item -ItemType Directory -Path $stage, $buildTemp, $ctpHouse, $offline | Out-Null
    # Always create a fresh per-run venv; an old or partial consumer is preserved untouched.
    $venvBatch = Join-Path $out 'create_consumer_venv.cmd'
    Write-Batch $venvBatch @('@echo off','setlocal','set "PYTHONPATH="','set "PYTHONHOME="','set "PYTHONNOUSERSITE=1"',('"{0}" -I -m venv "{1}"' -f $python311,$consumer),'exit /b %ERRORLEVEL%')
    Run-Batch $venvBatch 180 'create-consumer-venv' $out
    $consumerPython = Join-Path $consumer 'Scripts\python.exe'
    Assert-That (Test-Path -LiteralPath $consumerPython -PathType Leaf) 'Fresh consumer Python is missing.'
    $versionBatch = Join-Path $out 'check_python_version.cmd'
    Write-Batch $versionBatch @('@echo off','setlocal',('"{0}" -I -c "import sys; assert sys.version_info[:3] == (3,11,5), sys.version"' -f $consumerPython),'exit /b %ERRORLEVEL%')
    Run-Batch $versionBatch 30 'check-consumer-python' $out
    Expand-Archive -LiteralPath $ctpZip -DestinationPath $stage
    $ctpProject = Join-Path $stage 'bt_api_ctp'
    $toml = Get-Content -LiteralPath (Join-Path $ctpProject 'pyproject.toml') -Raw
    Assert-That ($toml -match '(?m)^name\s*=\s*["'']bt_api_ctp["'']\s*$') 'CTP project name mismatch.'
    Assert-That ($toml -match '(?m)^version\s*=\s*["'']2\.0\.4\+iteration41\.i9["'']\s*$') 'CTP source version mismatch.'
    Assert-That ($toml -match '(?m)^requires-python\s*=\s*["'']>=3\.9["'']\s*$') 'CTP Python requirement mismatch.'

    # The archived inputs are SDK-only; Backtrader must be supplied as a fresh current wheel.
    $logs = @('build.stdout.log','build.stderr.log','vcvars.log','compiler.log','compiler-environment.log') | ForEach-Object { Join-Path $out $_ }
    $batch = Join-Path $out 'build_ctp_wheel.cmd'
    Write-Batch $batch @(
        '@echo off','setlocal','set "PYTHONPATH="','set "PYTHONHOME="','set "PYTHONNOUSERSITE=1"',
        'set "PIP_CONFIG_FILE=NUL"','set "PIP_NO_INDEX="','set "PIP_EXTRA_INDEX_URL="','set "PIP_FIND_LINKS="','set "DISTUTILS_USE_SDK=1"','set "MSSdk=1"',
        ('set "TMP={0}"' -f $buildTemp),('set "TEMP={0}"' -f $buildTemp),
        ('call "{0}" x64 -vcvars_ver=14.42 > "{1}" 2>&1' -f $vcvars,$logs[2]),'if errorlevel 1 exit /b 71',
        ('if not "%VCToolsVersion%"=="{0}" exit /b 72' -f $clVersion),
        'set "FIRST_CL="','for /f "delims=" %%C in (''where cl'') do if not defined FIRST_CL set "FIRST_CL=%%C"',
        ('if /I not "%FIRST_CL%"=="{0}" exit /b 73' -f $clExpected),
        ('(echo VCINSTALLDIR=%VCINSTALLDIR%& echo VSCMD_VER=%VSCMD_VER%& echo VCToolsVersion=%VCToolsVersion%& echo FIRST_CL=%FIRST_CL%) > "{0}"' -f $logs[4]),
        ('where cl > "{0}" 2>&1' -f $logs[3]),
        ('"{0}" -I -m pip wheel --disable-pip-version-check --no-cache-dir --no-deps --index-url https://pypi.org/simple --wheel-dir "{1}" "{2}" 1>"{3}" 2>"{4}"' -f (Join-Path $consumer 'Scripts\python.exe'),$ctpHouse,$ctpProject,$logs[0],$logs[1]),
        'exit /b %ERRORLEVEL%'
    )
    Run-Batch $batch $BuildTimeoutSeconds 'build-ctp-wheel' $out
    $ctpWheels = @(Get-ChildItem -LiteralPath $ctpHouse -File -Filter '*.whl')
    Assert-That ($ctpWheels.Count -eq 1 -and $ctpWheels[0].Name -eq $ctpWheelName) 'CTP build did not produce the pinned CPython 3.11 x64 wheel.'
    $ctpPin = Pin $ctpWheels[0].FullName (Hash $ctpWheels[0].FullName)
    $manifest.phases.build = [ordered]@{ status = 'PASS'; stdout = $logs[0]; stderr = $logs[1]; vcvars = $logs[2]; compiler = $logs[3]; environment = $logs[4]; ctp_wheel = $ctpPin }
    $manifest.phase = 'build_complete'; Save-Manifest $manifestPath $manifest

    foreach ($wheel in $inventory.wheels) {
        if ($wheel.name -notin @('back-trader-python','bt_api_base')) { Copy-Item -LiteralPath (Join-Path $deps ([string]$wheel.filename)) -Destination $offline }
    }
    $offlineBtPath = Join-Path $offline ([IO.Path]::GetFileName($btPath))
    $offlineBasePath = Join-Path $offline ([IO.Path]::GetFileName($baseWheel))
    $offlineCtpPath = Join-Path $offline ([IO.Path]::GetFileName($ctpPin.path))
    Copy-Item -LiteralPath $btPath -Destination $offlineBtPath
    Copy-Item -LiteralPath $baseWheel -Destination $offlineBasePath
    Copy-Item -LiteralPath $ctpPin.path -Destination $offlineCtpPath
    $offlineBtPin = Pin $offlineBtPath $btPin.sha256 $btPin.size_bytes
    $offlineBasePin = Pin $offlineBasePath $basePin.sha256 $basePin.size_bytes
    $offlineCtpPin = Pin $offlineCtpPath $ctpPin.sha256 $ctpPin.size_bytes
    $offlineWheels = @(Get-ChildItem -LiteralPath $offline -File -Filter '*.whl')
    Assert-That ($offlineWheels.Count -eq ($pins.Count - 2 + 3)) 'Curated offline wheelhouse has an unexpected wheel count.'
    $offlineBtWheels = @(Get-ChildItem -LiteralPath $offline -File -Filter 'back_trader_python*.whl')
    Assert-That ($offlineBtWheels.Count -eq 1 -and $offlineBtWheels[0].FullName -ieq $offlineBtPath) 'Offline wheelhouse must contain exactly the supplied current Backtrader wheel.'
    Assert-That ($offlineBtPin.sha256 -ne [string]$oldBt[0].sha256) 'Offline Backtrader wheel matches the historical a69 wheel, not a fresh current artifact.'

    $installLogs = @('install.stdout.log','install.stderr.log') | ForEach-Object { Join-Path $out $_ }
    $installBatch = Join-Path $out 'install_consumer_offline.cmd'
    Write-Batch $installBatch @(
        '@echo off','setlocal','set "PYTHONPATH="','set "PYTHONHOME="','set "PYTHONNOUSERSITE=1"','set "PIP_CONFIG_FILE=NUL"',
        ('"{0}" -I -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: --no-index --find-links "{1}" "{2}" "{3}" "{4}" 1>"{5}" 2>"{6}"' -f $consumerPython,$offline,$offlineBtPath,$offlineBasePath,$offlineCtpPath,$installLogs[0],$installLogs[1]),
        'exit /b %ERRORLEVEL%'
    )
    Run-Batch $installBatch $InstallTimeoutSeconds 'install-consumer-offline' $out
    $manifest.phases.install = [ordered]@{ status = 'PASS'; index = 'disabled'; wheelhouse = $offline; selected_wheels = @($offlineBtPin, $offlineBasePin, $offlineCtpPin); stdout = $installLogs[0]; stderr = $installLogs[1] }
    $manifest.phase = 'install_complete'; Save-Manifest $manifestPath $manifest

    $checkLogs = @('pip-check.stdout.log','pip-check.stderr.log') | ForEach-Object { Join-Path $out $_ }
    $checkBatch = Join-Path $out 'pip_check.cmd'
    Write-Batch $checkBatch @('@echo off','setlocal','set "PYTHONPATH="','set "PYTHONHOME="','set "PYTHONNOUSERSITE=1"','set "PIP_CONFIG_FILE=NUL"',('"{0}" -I -m pip check 1>"{1}" 2>"{2}"' -f $consumerPython,$checkLogs[0],$checkLogs[1]),'exit /b %ERRORLEVEL%')
    Run-Batch $checkBatch $CheckTimeoutSeconds 'consumer-pip-check' $out

    $verifier = Join-Path $out 'verify_consumer.py'
    $verifyLogs = @('verify.stdout.log','verify.stderr.log') | ForEach-Object { Join-Path $out $_ }
    [IO.File]::WriteAllText($verifier, @'
import base64, csv, hashlib, importlib, importlib.metadata, importlib.machinery, json, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
if Path(sys.prefix).resolve() != root or sys.version_info[:3] != (3, 11, 5): raise SystemExit("consumer interpreter mismatch")
expected = {"back-trader-python":"1.4.0", "bt-api-base":"0.15.8", "bt-api-ctp":"2.0.4+iteration41.i9"}
records = {}
for name, version in expected.items():
    dist = importlib.metadata.distribution(name)
    if dist.version != version: raise SystemExit(f"{name} version mismatch: {dist.version}")
    checked = 0
    for rel, digest, size in csv.reader(dist.read_text("RECORD").splitlines()):
        path = Path(dist.locate_file(rel)).resolve(); path.relative_to(root)
        if not path.is_file() or (size and path.stat().st_size != int(size)): raise SystemExit(f"{name} RECORD mismatch: {rel}")
        if digest:
            algorithm, expected_hash = digest.split("=", 1); h = hashlib.new(algorithm)
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""): h.update(block)
            actual = base64.urlsafe_b64encode(h.digest()).rstrip(b"=").decode("ascii")
            if actual != expected_hash: raise SystemExit(f"{name} RECORD hash mismatch: {rel}")
            checked += 1
    if not checked: raise SystemExit(f"{name} RECORD has no hashed entries")
    records[name] = {"version":dist.version,"hashed_entries_verified":checked}
import backtrader, bt_api_base, bt_api_ctp
from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
if not callable(getattr(ExecutionDecisionJournal, "decision_for_key", None)): raise SystemExit("current journal API is missing")
from bt_api_ctp.ctp import _ctp_base
native = importlib.import_module("bt_api_ctp.ctp._ctp")
modules = {"backtrader":Path(backtrader.__file__).resolve(),"bt_api_base":Path(bt_api_base.__file__).resolve(),"bt_api_ctp":Path(bt_api_ctp.__file__).resolve(),"bt_api_ctp.ctp._ctp":Path(native.__file__).resolve()}
for path in modules.values(): path.relative_to(root)
if not any(str(modules["bt_api_ctp.ctp._ctp"]).endswith(s) for s in importlib.machinery.EXTENSION_SUFFIXES): raise SystemExit("CTP origin is not a CPython extension")
if not _ctp_base.is_ctp_native_loaded(): raise SystemExit("CTP selected its fallback")
print(json.dumps({"status":"PASS","records":records,"origins":{k:str(v) for k,v in modules.items()},"ctp_native_loaded":True},sort_keys=True))
'@, [Text.Encoding]::UTF8)
    $verifyBatch = Join-Path $out 'verify_consumer.cmd'
    Write-Batch $verifyBatch @('@echo off','setlocal','set "PYTHONPATH="','set "PYTHONHOME="','set "PYTHONNOUSERSITE=1"',('"{0}" -I "{1}" "{2}" 1>"{3}" 2>"{4}"' -f $consumerPython,$verifier,$consumer,$verifyLogs[0],$verifyLogs[1]),'exit /b %ERRORLEVEL%')
    Run-Batch $verifyBatch $CheckTimeoutSeconds 'consumer-record-origin-verification' $out
    $verified = Get-Content -LiteralPath $verifyLogs[0] -Raw | ConvertFrom-Json
    Assert-That ($verified.status -eq 'PASS' -and $verified.ctp_native_loaded -eq $true) 'Consumer verification did not pass.'
    $manifest.phases.pip_check = [ordered]@{ status = 'PASS'; stdout = $checkLogs[0]; stderr = $checkLogs[1] }
    $manifest.phases.verification = [ordered]@{ status = 'PASS'; result = $verified; stdout = $verifyLogs[0]; stderr = $verifyLogs[1] }
    $manifest.phase = 'complete'; $manifest.status = 'PASS'; Save-Manifest $manifestPath $manifest
    Write-Host "R0 consumer verification passed: $manifestPath"
}
catch {
    $manifest.status = 'FAIL'; $manifest.phase = 'failed'; $manifest.failure = [string]$_.Exception.Message
    Save-Manifest $manifestPath $manifest
    throw
}
