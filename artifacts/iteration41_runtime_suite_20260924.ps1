$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'D:\source_code\backtrader'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$logPath = 'D:\source_code\backtrader\artifacts\iteration41_runtime_suite_20260924.log'
$exitPath = 'D:\source_code\backtrader\artifacts\iteration41_runtime_suite_20260924.exit'
& python -m pytest tests/unit/runtime -q --disable-warnings *> $logPath
$result = $LASTEXITCODE
Set-Content -LiteralPath $exitPath -Value $result -NoNewline -Encoding ascii
exit $result
