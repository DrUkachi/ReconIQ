param(
    [string]$Bank = 'tests/fixtures/signed_exports/Bank_Statement_Demo.pdf',
    [string]$Ledger = 'tests/fixtures/signed_exports/General_Ledger_Demo.csv'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$localRoot = Join-Path $repoRoot '.local'
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$postgresExe = Join-Path $localRoot 'postgres\pgsql\bin\postgres.exe'
$readyExe = Join-Path $localRoot 'postgres\pgsql\bin\pg_isready.exe'
$dataDir = Join-Path $localRoot 'pgdata'
$passwordFile = Join-Path $localRoot 'postgres-password'
foreach ($requiredPath in @($pythonExe, $postgresExe, $readyExe, $dataDir, $passwordFile)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw 'The local demo runtime is not provisioned. Configure DATABASE_URL and use python -m scripts.reconcile_inputs instead.'
    }
}

Push-Location $repoRoot
$previousDatabaseUrl = $env:DATABASE_URL
try {
    & $readyExe -h 127.0.0.1 -p 55439 -q
    if ($LASTEXITCODE -ne 0) {
        Start-Process -FilePath $postgresExe -ArgumentList @(
            '-D', ('"' + $dataDir + '"'), '-h', '127.0.0.1', '-p', '55439'
        ) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $localRoot 'postgres-out.log') `
            -RedirectStandardError (Join-Path $localRoot 'postgres-error.log') | Out-Null
        for ($attempt = 0; $attempt -lt 50; $attempt++) {
            Start-Sleep -Milliseconds 100
            & $readyExe -h 127.0.0.1 -p 55439 -q
            if ($LASTEXITCODE -eq 0) { break }
        }
        if ($LASTEXITCODE -ne 0) { throw 'Local PostgreSQL did not become ready. See .local/postgres-error.log.' }
    }
    $dbPassword = Get-Content -LiteralPath $passwordFile -Raw
    $env:DATABASE_URL = 'postgresql+asyncpg://reconiq_local:' + $dbPassword + '@127.0.0.1:55439/reconiq_demo'
    & $pythonExe -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    & $pythonExe -m scripts.reconcile_inputs --demo --account-last4 DEMO `
        --bank $Bank --ledger $Ledger --period-start 2026-08-01 --period-end 2026-08-31
    if ($LASTEXITCODE -ne 0) { throw 'Reconciliation failed.' }
} finally {
    $env:DATABASE_URL = $previousDatabaseUrl
    Pop-Location
}
