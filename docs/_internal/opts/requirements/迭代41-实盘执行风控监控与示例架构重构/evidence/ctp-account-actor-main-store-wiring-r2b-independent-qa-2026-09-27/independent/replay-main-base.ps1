$ErrorActionPreference='Stop'
$qa='D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2b-independent-qa-20260927-v1'
$replay=Join-Path $qa 'patch-replay'
$src='D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2b'
$base=Join-Path $replay 'input-sources/btapistore.py'
$patch=Join-Path $qa 'r2b-main-base-apply.patch'
$log=Join-Path $qa 'patch-replay.log'
$lines=@()
Push-Location $replay
try {
  git -c core.autocrlf=false apply -R --check $patch
  $lines += "reverse_check_exit=$LASTEXITCODE"
  git -c core.autocrlf=false apply -R $patch
  $lines += "reverse_apply_exit=$LASTEXITCODE"
  Copy-Item -LiteralPath $base -Destination (Join-Path $replay 'backtrader/stores/btapistore.py') -Force
  $baseHash=(Get-FileHash -LiteralPath (Join-Path $replay 'backtrader/stores/btapistore.py') -Algorithm SHA256).Hash.ToLowerInvariant()
  $lines += "authoritative_main_base_store_sha256=$baseHash"
  if($baseHash -ne 'dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826'){throw 'main base Store hash mismatch'}
  git -c core.autocrlf=false apply --check $patch
  $lines += "forward_check_exit=$LASTEXITCODE"
  git -c core.autocrlf=false apply $patch
  $lines += "forward_apply_exit=$LASTEXITCODE"
} finally { Pop-Location }
$manifest=Get-Content -Raw -LiteralPath (Join-Path $src 'evidence/r2b-manifest.json') | ConvertFrom-Json
$changed=@('backtrader/stores/btapistore.py','backtrader/stores/ctp_account_actor_port.py','tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py','tests/unit/stores/test_managed_ctp_store_adapter.py','tests/unit/stores/test_ctp_non_authorizing_contracts.py')
foreach($rel in $changed){$file=Join-Path $replay $rel;$got=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant();$expect=($manifest.files | Where-Object path -eq $rel).sha256;if($got -ne $expect){throw "replayed target mismatch $rel $got != $expect"};$lines += "target $rel $got"}
$lines += 'PATCH_REPLAY_OK'
$lines | Set-Content -LiteralPath $log -Encoding utf8
$lines | ForEach-Object {Write-Output $_}