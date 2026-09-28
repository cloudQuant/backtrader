$ErrorActionPreference = 'Stop'
$archive = 'D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-g1-overlapped-io-custody-main-2026-09-28'
$repo = 'D:\source_code\backtrader'
function Sha([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower() }
function Rel([string]$Path) { $Path.Substring($archive.Length).TrimStart('\').Replace('\', '/') }

$expectedArchive = @{
  'candidate/PATCH.diff' = 'c27ddf0d605a9705956dff9ba00b05f3b6640492162c8e58f4e07d4791a44bdd'
  'candidate/FROZEN-MANIFEST.json' = '074235d2ff29afb6256ef385f29f5c6b7a9e84be8eacbb3bc3fb4fbaa472668c'
  'qa/INDEPENDENT-QA-RECEIPT.md' = '423a79a759c1e1181f7e2da57932c8eb8f22b696ec11683e1df7d576cf016089'
  'qa/qa-extra-test-source.py' = 'd5316f7a3b4d0a163684c777e0bbb59b70bce94d9725134e26c01d35c17f158b'
}
foreach ($entry in $expectedArchive.GetEnumerator()) {
  if ((Sha (Join-Path $archive $entry.Key)) -ne $entry.Value) { throw "Expected archive hash mismatch: $($entry.Key)" }
}
$sourceSha = Sha (Join-Path $repo 'scripts\ctp_i13_i15_worker_output_channel.py')
$testSha = Sha (Join-Path $repo 'tests\unit\scripts\test_ctp_i13_i15_worker_output_channel.py')
if ($sourceSha -ne '4f9ff31428cdfd9d62acc8118ae4bb00bc09cc0e5883fb07c6b1daea85f41178') { throw 'Main source hash mismatch' }
if ($testSha -ne '25332e48979f7827fa97e5dc4c8fa4fb7acd8eb17262c505bde4f4afec182861') { throw 'Main test hash mismatch' }

$mainSuite = ([xml](Get-Content -LiteralPath (Join-Path $archive 'main-focus\junit.xml') -Raw)).SelectSingleNode('//testsuite[@tests]')
$adjXml = [xml](Get-Content -LiteralPath (Join-Path $archive 'adjacent-suite\junit.xml') -Raw)
$adjSuite = $adjXml.SelectSingleNode('//testsuite[@tests]')
$qaSuite = ([xml](Get-Content -LiteralPath (Join-Path $archive 'qa\qa-focus-junit.xml') -Raw)).SelectSingleNode('//testsuite[@tests]')
if ([int]$mainSuite.tests -ne 33 -or [int]$mainSuite.failures -ne 0) { throw 'Main JUnit assertion failed' }
if ([int]$adjSuite.tests -ne 305 -or [int]$adjSuite.failures -ne 0) { throw 'Adjacent JUnit assertion failed' }
if ([int]$qaSuite.tests -ne 36 -or [int]$qaSuite.failures -ne 0) { throw 'QA JUnit assertion failed' }
foreach ($path in @('main-focus\exit.txt', 'adjacent-suite\exit.txt', 'qa\qa-focus-exit.txt', 'inventory\exit.txt')) {
  if ((Get-Content -Raw (Join-Path $archive $path)).Trim() -ne '0') { throw "Nonzero exit recorded in $path" }
}
$mainGuard = Get-Content -Raw (Join-Path $archive 'main-focus\guard-logs\23572.json') | ConvertFrom-Json
$adjGuard = Get-Content -Raw (Join-Path $archive 'adjacent-suite\guard-logs\27784.json') | ConvertFrom-Json
foreach ($guard in @($mainGuard, $adjGuard)) {
  if ($guard.events.Count -ne 0 -or $guard.native_modules_loaded.Count -ne 0) { throw 'Guard evidence is not empty' }
}
$inventory = Get-Content -Raw (Join-Path $archive 'inventory\no-change-result.json') | ConvertFrom-Json
if ($inventory.status -ne 'NO_CHANGE' -or -not $inventory.comparison.writer_rows_exact_and_ordered -or -not $inventory.comparison.dynamic_rows_exact_and_ordered) { throw 'Inventory comparison failed' }
if ($inventory.comparison.changed_channel_script_candidate_rows.Count -ne 0) { throw 'Channel script has inventory candidates' }
if ((Sha (Join-Path $repo 'docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\live-execution-inventory-candidates.json')) -ne '0874a81ac23ba4f659acaac833a976ecec44fa892a3a97778ea3d9779db67a67') { throw 'Current inventory baseline hash mismatch' }

$readme = Get-Content -Raw (Join-Path $archive 'README.md')
if ($readme -match 'DRAFT' -or $readme -notmatch 'Strict whole-command G1 remains `NO_GO`') { throw 'README status wording assertion failed' }
$linkMatches = [regex]::Matches($readme, '\]\(([^)]+)\)')
$missingLinks = @()
foreach ($match in $linkMatches) {
  $target = $match.Groups[1].Value
  if ($target -match '^(https?:|#)') { continue }
  if (-not (Test-Path -LiteralPath (Join-Path $archive $target))) { $missingLinks += $target }
}
if ($missingLinks.Count -gt 0) { throw ('Broken README links: ' + ($missingLinks -join ', ')) }

$external = @(
  [pscustomobject]@{ path = 'scripts/ctp_i13_i15_worker_output_channel.py'; sha256 = $sourceSha },
  [pscustomobject]@{ path = 'tests/unit/scripts/test_ctp_i13_i15_worker_output_channel.py'; sha256 = $testSha },
  [pscustomobject]@{ path = 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/live-execution-inventory-candidates.json'; sha256 = Sha (Join-Path $repo 'docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\live-execution-inventory-candidates.json') }
)
$files = @(Get-ChildItem -LiteralPath $archive -Recurse -File | Where-Object { $_.Name -notin @('ARTIFACT-MANIFEST.json', 'SHA256SUMS.txt') } | Sort-Object { Rel $_.FullName } | ForEach-Object { [pscustomobject]@{ path = (Rel $_.FullName); sha256 = (Sha $_.FullName); bytes = $_.Length } })
$modules = @($adjXml.SelectNodes('//testcase') | ForEach-Object { $_.classname } | Sort-Object -Unique)
$manifest = [ordered]@{
  schema = 'iteration41_g1_overlapped_io_custody_main_archive.v1'
  date = '2026-09-28'
  status = 'GO_LOCAL_SUBGATE_ONLY; STRICT_WHOLE_COMMAND_G1_NO_GO; ORDINARY_PREFLIGHT_CLOSED'
  files = $files
  external_references = $external
  verification = [ordered]@{
    main_focus = '33 passed, 0 failed, exit 0'
    adjacent_guarded_suite = '305 passed, 0 failed, exit 0; 12 test modules'
    adjacent_test_modules = $modules
    independent_qa = 'GO_LOCAL_SUBGATE; 36 passed, Ruff clean, py_compile exit 0'
    inventory = 'NO_CHANGE; 363 writer + 97 dynamic across 355 scanned files; zero parse errors/unclassified paths; exact ordered rows and locations'
    guard = 'main and adjacent logs both have zero events and zero native modules'
  }
  limits = 'Does not bound synchronous Win32 calls, SCM/CLI startup or Windows scheduling. A prewarmed service request SLA is not the whole-command startup-inclusive deadline.'
}
$manifestPath = Join-Path $archive 'ARTIFACT-MANIFEST.json'
[IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 10) + "`n", [Text.UTF8Encoding]::new($false))
$sumFiles = @(Get-ChildItem -LiteralPath $archive -Recurse -File | Where-Object { $_.Name -ne 'SHA256SUMS.txt' } | Sort-Object { Rel $_.FullName })
$sumLines = @()
foreach ($file in $sumFiles) { $sumLines += ((Sha $file.FullName) + '  ' + (Rel $file.FullName)) }
$sumsPath = Join-Path $archive 'SHA256SUMS.txt'
[IO.File]::WriteAllText($sumsPath, ($sumLines -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
[pscustomobject]@{
  readme_sha256 = Sha (Join-Path $archive 'README.md')
  manifest_sha256 = Sha $manifestPath
  sha256sums_sha256 = Sha $sumsPath
  indexed_files = $sumFiles.Count
  validated_readme_links = $linkMatches.Count
  main_tests = [int]$mainSuite.tests
  adjacent_tests = [int]$adjSuite.tests
  qa_tests = [int]$qaSuite.tests
  inventory_status = $inventory.status
  changed_inventory_rows = 0
} | ConvertTo-Json -Depth 4