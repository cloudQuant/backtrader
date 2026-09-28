$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'D:\source_code\backtrader'
$logPath = 'D:\source_code\backtrader\artifacts\iteration41_offline_smoke_20260924.log'
$exitPath = 'D:\source_code\backtrader\artifacts\iteration41_offline_smoke_20260924.exit'
& python scripts/ci/smoke_iteration41_registered_offline.py *> $logPath
$result = $LASTEXITCODE
Set-Content -LiteralPath $exitPath -Value $result -NoNewline -Encoding ascii
exit $result
