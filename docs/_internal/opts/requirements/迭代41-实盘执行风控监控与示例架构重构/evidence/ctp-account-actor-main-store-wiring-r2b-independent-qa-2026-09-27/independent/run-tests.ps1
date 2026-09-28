$ErrorActionPreference = 'Continue'
$qa = 'D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2b-independent-qa-20260927-v1'
$root = Join-Path $qa 'candidate'
$out = Join-Path $qa 'run-artifacts'
$python = 'C:\Users\yunji\AppData\Local\Temp\bt-pytest-asyncio-compat-20260926\Scripts\python.exe'
foreach ($item in Get-ChildItem Env:) {
    if ($item.Name -match '^(BT_|CTP_|PYTHONPATH$|PYTEST_)') { Remove-Item ("Env:" + $item.Name) -ErrorAction SilentlyContinue }
}
$env:PYTHONPATH = $root
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPYCACHEPREFIX = Join-Path $qa 'pycache-outside-source'
$results = @()
Push-Location $root
try {
    $runs = @(
        @{Name='route-boundary'; Args=@('-B','-m','pytest','-p','no:asyncio','-p','no:cacheprovider','tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py::test_internal_legacy_and_cancel_ref_helpers_recheck_mutated_ctp_route','tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py::test_gateway_wrapper_submit_cancel_recheck_store_route_after_mutation','-q','--tb=short',("--junitxml=" + (Join-Path $out 'junit/route-boundary.xml')))},
        @{Name='candidate-focus'; Args=@('-B','-m','pytest','-p','no:asyncio','-p','no:cacheprovider','tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py','tests/unit/stores/test_managed_ctp_store_adapter.py','-q','--tb=short',("--junitxml=" + (Join-Path $out 'junit/candidate-focus.xml')))},
        @{Name='legacy-30'; Args=@('-B','-m','pytest','-p','no:asyncio','-p','no:cacheprovider','tests/unit/stores/test_managed_execution_store_adapter.py','tests/unit/stores/test_managed_ctp_store_adapter.py','tests/unit/runtime/test_runtime_live_dispatch_guard.py','-q','--tb=short',("--junitxml=" + (Join-Path $out 'junit/legacy-30.xml')))},
        @{Name='stores-runtime-55'; Args=@('-B','-m','pytest','-p','no:asyncio','-p','no:cacheprovider','tests/unit/stores','tests/unit/runtime','-q','--tb=short',("--junitxml=" + (Join-Path $out 'junit/stores-runtime-55.xml')))}
    )
    foreach ($run in $runs) {
        $cmdline = 'python ' + ($run.Args -join ' ')
        Set-Content -LiteralPath (Join-Path $out ("commands/" + $run.Name + '.txt')) -Value $cmdline -Encoding utf8
        Write-Output ("=== " + $run.Name + " ===")
        Write-Output $cmdline
        & $python @($run.Args) 2>&1 | Tee-Object -FilePath (Join-Path $out ("logs/" + $run.Name + '.log'))
        $code = $LASTEXITCODE
        Write-Output ("EXIT_CODE=" + $code)
        Add-Content -LiteralPath (Join-Path $out ("logs/" + $run.Name + '.log')) -Value ("EXIT_CODE=" + $code) -Encoding utf8
        $results += [PSCustomObject]@{Name=$run.Name; ExitCode=$code}
    }
} finally { Pop-Location }
$results | Format-Table -AutoSize
if (($results | Where-Object ExitCode -ne 0).Count -gt 0) { exit 1 } else { exit 0 }