param(
    [string]$Port = 'COM3',
    [ValidateSet('off', 'on')][string]$Profile = 'on',
    [ValidateRange(1, 10)][int]$Repetitions = 3,
    [ValidateRange(1, 2000)][int]$PauseMs = 500,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$pythonPath = Join-Path $repoRoot '.venv/Scripts/python.exe'
$benchmarkPath = Join-Path $PSScriptRoot 'testboard_7953_benchmark.py'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw "Python environment missing: $pythonPath" }
$sessionPrefix = 'live_usb_' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$commonArguments = @(
    '--port', $Port, '--profile', $Profile, '--scan-order', 'adc',
    '--tests', '__manual__lpspi__repeat1__vmidoff__',
    '--warm-up-ms', '1000', '--window-ms', '5000',
    '--repetitions', "$Repetitions", '--seed', '7953', '--no-drift-controls'
)

function Invoke-LiveBenchmark([string]$Name, [string[]]$CaseArguments) {
    $resultPath = Join-Path $PSScriptRoot "results/${sessionPrefix}_${Name}"
    $benchmarkArguments = $commonArguments + $CaseArguments + @('--output', $resultPath)
    if ($DryRun) { $benchmarkArguments += '--dry-run' }
    Write-Host "Live USB validation: $Name"
    & $pythonPath $benchmarkPath @benchmarkArguments
    if ($LASTEXITCODE -ne 0) { throw "Live USB validation failed: $Name" }
}

# 9 normal captures, then 3 for the earlier ADC3 noise exception, and two
# 3-capture reader controls: 18 captures by default. No GUI or board upload.
Invoke-LiveBenchmark 'normal20' @(
    '--spi-clock-hz', '20000000', '--route-set', 'full_array1',
    '--route-set', 'all_four_full', '--route-set', 'one_adc_bus2'
)
Invoke-LiveBenchmark 'adc3_10' @('--spi-clock-hz', '10000000', '--route-set', 'one_adc_bus2')
Invoke-LiveBenchmark 'deferred20' @('--spi-clock-hz', '20000000', '--route-set', 'all_four_full', '--defer-parsing')
Invoke-LiveBenchmark "pause${PauseMs}ms20" @(
    '--spi-clock-hz', '20000000', '--route-set', 'all_four_full',
    '--defer-parsing', '--reader-pause-ms', "$PauseMs", '--reader-pause-at-ms', '2000'
)
Write-Host "Validation commands finished. Results prefix: $sessionPrefix"
