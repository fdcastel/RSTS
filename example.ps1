#!/usr/bin/env pwsh
# example.ps1 — Demonstrates a stateful workload migration using RSTS (no Docker).
#
# Requirements: uv (https://docs.astral.sh/uv/)
# Compatible with PowerShell 7+ on Windows and Linux.
#
# Scenario:
#   1. Start RSTS on "location A" (temp/rsts/location-a)
#   2. Write some state to it
#   3. Stop the process (simulating decommission)
#   4. Start RSTS on "location B" (temp/rsts/location-b) with the SAME data volume
#   5. Verify state survived and instance changed (proving relocation, not restart)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$AppUrl     = "https://raw.githubusercontent.com/fdcastel/RSTS/master/app.py"
$Port       = 8080
$TempRoot   = Join-Path ([System.IO.Path]::GetTempPath()) "rsts"
$DataSrc    = Join-Path $TempRoot "location-a"
$DataDst    = Join-Path $TempRoot "location-b"
$StateValue = "migrated-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"

function Wait-Ready {
    param([int]$Port)
    do {
        Start-Sleep -Milliseconds 500
        $ready = $false
        try {
            $null = Invoke-RestMethod "http://localhost:$Port/health"
            $ready = $true
        } catch {}
    } until ($ready)
}

function Start-Rsts {
    param(
        [string]$DataDir,
        [string]$ServerName,
        [int]$Port
    )
    $env:RSTS_DATA_DIR    = $DataDir
    $env:RSTS_SERVER_NAME = $ServerName
    $env:RSTS_PORT        = "$Port"
    $proc = Start-Process uv -ArgumentList @("run", $AppUrl) -PassThru -NoNewWindow
    $env:RSTS_DATA_DIR    = $null
    $env:RSTS_SERVER_NAME = $null
    $env:RSTS_PORT        = $null
    return $proc
}

Write-Host "=== RSTS Migration Demo (uv) ===" -ForegroundColor Cyan
Write-Host ""

# --- Prepare storage locations ---
Write-Host "[1/7] Preparing storage locations..."
New-Item -ItemType Directory -Force -Path $DataSrc, $DataDst | Out-Null

# --- Start on Location A ---
Write-Host "[2/7] Starting RSTS on Location A ($DataSrc)..."
$ProcA = Start-Rsts -DataDir $DataSrc -ServerName "location-a" -Port $Port

Write-Host "      Waiting for service to be ready..."
Wait-Ready -Port $Port

# --- Inspect initial state ---
Write-Host "[3/7] Initial state on Location A:"
$StatusA = Invoke-RestMethod "http://localhost:$Port/"
$StatusA | ConvertTo-Json -Depth 5
Write-Host ""

$InstanceA = $StatusA.instance_id

# --- Write meaningful state ---
Write-Host "[4/7] Writing state '$StateValue' to Location A..."
Invoke-RestMethod -Method Post "http://localhost:$Port/state/$StateValue" | ConvertTo-Json
Write-Host ""

# --- Copy data volume to destination ---
Write-Host "[5/7] Migrating data volume: $DataSrc -> $DataDst..."
Get-ChildItem -Path $DataSrc | Copy-Item -Destination $DataDst -Recurse -Force
Write-Host "      Done. Contents: $(Get-ChildItem $DataDst | Select-Object -ExpandProperty Name)"

# --- Stop Location A ---
Write-Host "[6/7] Stopping Location A..."
$ProcA.Kill($true)
$ProcA.WaitForExit()

# --- Start on Location B with migrated data ---
Write-Host "      Starting RSTS on Location B ($DataDst)..."
$ProcB = Start-Rsts -DataDir $DataDst -ServerName "location-b" -Port $Port

Write-Host "      Waiting for service to be ready..."
Wait-Ready -Port $Port

# --- Verify migration ---
Write-Host "[7/7] State on Location B after migration:"
$StatusB = Invoke-RestMethod "http://localhost:$Port/"
$StatusB | ConvertTo-Json -Depth 5
Write-Host ""

$InstanceB  = $StatusB.instance_id
$DataValueB = $StatusB.data

Write-Host "=== Migration Verification ===" -ForegroundColor Cyan
Write-Host "  State value    : $DataValueB  (expected: $StateValue)"
Write-Host "  Instance A ID  : $InstanceA"
Write-Host "  Instance B ID  : $InstanceB"
Write-Host ""

if ($DataValueB -eq $StateValue) {
    Write-Host "  [PASS] State survived the migration." -ForegroundColor Green
} else {
    Write-Host "  [FAIL] State was lost!" -ForegroundColor Red
}

if ($InstanceA -ne $InstanceB) {
    Write-Host "  [PASS] Instance ID changed — this is a relocation, not a mere restart." -ForegroundColor Green
} else {
    Write-Host "  [FAIL] Instance ID is the same — something is wrong." -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Cleanup ===" -ForegroundColor Cyan
$ProcB.Kill($true)
$ProcB.WaitForExit()
Remove-Item -Recurse -Force $TempRoot
Write-Host "Done."
