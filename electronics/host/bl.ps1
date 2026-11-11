# One-step host for the KSPEC-BL Uno firmware on Windows, without Python (PowerShell 5.1,
# System.IO.Ports). Same frames and rules as bl_cycle.py; one step per call so a person can watch
# the hardware between steps (bench session 2026-10-23, note 2026-10-14-bench-sbc-stage).
#
#   bl.ps1 -Lines "PING","L ?"             firmware lines
#   bl.ps1 -Limits                          read Near/Far
#   bl.ps1 -GoHome                          Near at 2 mm/s, IR1 Low-stop, bounded 155 mm
#   bl.ps1 -MoveMm 130 -Far [-Speed 16000]  bounded relative move (-Far = down/IN, else up/Near)
#   bl.ps1 -MoveMm 8 -Speed 1600            final Near approach at 1 mm/s (lost-step check)
#   bl.ps1 -LightSec 10                     L MAIN ON, hold (PING), L MAIN OFF in the same call
#   bl.ps1 -Lines "WDTFRAME 0106002D0001" -Release   motor current off at rest
#
# The first open after the Uno is plugged in resets it (DTR); later opens with DtrEnable off do
# not. The Uno watchdog (60 s) is never PINGed between calls, so the light only stays on inside a
# -LightSec call. Every call sets WDTFRAME to stop-and-hold; use the release frame at rest, else
# the watchdog re-energises the motor 60 s after the last call. The script exits 0 or 1, so calls
# can be chained with `if ($LASTEXITCODE -eq 0)`.
param(
    [string[]]$Lines = @(),
    [switch]$Limits, [switch]$GoHome, [switch]$Release,
    [double]$MoveMm = 0, [switch]$Far, [int]$Speed = 16000,
    [double]$LightSec = 0,
    [string]$Port = "COM3"
)
$ErrorActionPreference = "Stop"
$STEPS_PER_MM = 1600
$IN_LIMIT_MM = 140  # never below IN on the instrument (bl_cycle.py)
$t0 = Get-Date
function Log($m) { Write-Host ("[{0,6:N1}] {1}" -f ((Get-Date) - $t0).TotalSeconds, $m) }
function Hex([byte[]]$b) { ($b | ForEach-Object { $_.ToString("X2") }) -join "" }
function Wr32([int]$reg, [uint32]$val) {
    $v = [BitConverter]::GetBytes($val); [Array]::Reverse($v)
    Hex (@(1, 0x10, 0, $reg, 0, 2, 4) + $v)
}
function MoveWord([double]$mm, [bool]$far) {
    # 0x002B relative move; only the limit in the direction of travel is enabled (stop on Low)
    $steps = [uint32][math]::Round($mm * $STEPS_PER_MM)
    if ($steps -le 0 -or $steps -gt 0xFFFFFF) { throw "bad step count $steps" }
    if ($far) { return [uint32](0x80000000 -bor (1 -shl 27) -bor (1 -shl 25) -bor $steps) }
    [uint32]((1 -shl 26) -bor (1 -shl 24) -bor $steps)
}

$sp = New-Object System.IO.Ports.SerialPort $Port, 9600, "None", 8, "One"
$sp.DtrEnable = $false; $sp.RtsEnable = $false
$sp.NewLine = "`n"; $sp.ReadTimeout = 1500
$sp.Open()
Start-Sleep -Milliseconds 2500
$boot = $sp.ReadExisting().Trim()
if ($boot) { Log "on open: $boot" }

function Send($line, [switch]$Quiet) {
    $sp.DiscardInBuffer(); $sp.WriteLine($line)
    try { $r = $sp.ReadLine().Trim() } catch { $r = "(no reply)" }
    if (-not $Quiet) { Log ("{0,-34} -> {1}" -f $line, $r) }
    return $r
}
function MB($hex) {
    # never resent: moves are relative
    $r = Send ("MB " + $hex)
    if ($r -notmatch '^OK') { throw "SBC did not answer ($r); position is invalid, re-home" }
}
function ReadLimits([switch]$Quiet) {
    # 0x002E: bit0 = IR1 = Near, bit1 = IR2 = Far, pressed = 0
    $r = Send "MB 0103002E0001" -Quiet
    if ($r -notmatch '^OK 010302([0-9A-F]{4})') { throw "limit read failed: $r" }
    $v = [Convert]::ToInt32($Matches[1], 16)
    $near = -not ($v -band 1); $far = -not ($v -band 2)
    if (-not $Quiet) { Log ("LIMITS Near={0} Far={1}" -f $(if ($near) { 'PRESSED' } else { 'open' }), $(if ($far) { 'PRESSED' } else { 'open' })) }
    return , @($near, $far)
}

try {
    $null = Send "WDTFRAME 0106002D0000"   # watchdog expiry also stops the stage
    foreach ($l in $Lines) { $null = Send $l }
    if ($Limits) { $null = ReadLimits }
    if ($GoHome) {
        if ((ReadLimits)[0]) { Log "already at Near" }
        else {
            MB (Wr32 0x28 3200)
            MB (Wr32 0x2B (MoveWord 155 $false))
            $t = Get-Date; $ok = $false
            while (((Get-Date) - $t).TotalSeconds -lt 82.5) {
                if ((ReadLimits -Quiet)[0]) { $ok = $true; break }
                Start-Sleep -Milliseconds 100
            }
            $s = ((Get-Date) - $t).TotalSeconds
            if (-not $ok) { throw "Near not reached while homing" }
            Log ("HOME: Near after {0:N1} s (~{1:N1} mm travelled)" -f $s, ($s * 2))
        }
    }
    if ($MoveMm -gt 0) {
        if ($MoveMm -gt $IN_LIMIT_MM) { throw "max $IN_LIMIT_MM mm (IN soft limit)" }
        if ($Speed -lt 1600 -or $Speed -gt 16000) { throw "speed out of 1600..16000 step/s" }
        MB (Wr32 0x28 ([uint32]$Speed))   # resets to 3200 at SBC power-up: always rewrite
        MB (Wr32 0x2B (MoveWord $MoveMm $Far.IsPresent))
        $dt = $MoveMm * $STEPS_PER_MM / $Speed + 1.5
        Log ("MOVE {0} mm {1} at {2} mm/s, ~{3:N1} s" -f $MoveMm, $(if ($Far) { 'DOWN/Far' } else { 'UP/Near' }), ($Speed / $STEPS_PER_MM), $dt)
        $end = (Get-Date).AddSeconds($dt)
        while ((Get-Date) -lt $end) {
            $l = ReadLimits -Quiet
            if (($Far -and $l[1]) -or (-not $Far -and $l[0])) { Log "limit tripped during the move"; break }
            Start-Sleep -Milliseconds 200
        }
        $null = ReadLimits
    }
    if ($LightSec -gt 0) {
        $null = Send "L MAIN ON"
        $end = (Get-Date).AddSeconds($LightSec)
        while ((Get-Date) -lt $end) { Start-Sleep -Seconds ([math]::Min(10, [math]::Max(0.1, ($end - (Get-Date)).TotalSeconds))); $null = Send "PING" -Quiet }
        $null = Send "L MAIN OFF"
    }
    if ($Release) { MB "0106002D0001" }   # the lead screw is not back-drivable: release at rest
    $null = Send "L ?"
}
catch {
    Log "ABORT: $_"
    try { $null = Send "L OFF"; $null = Send "MB 0106002D0000" } catch {}
    Log "light off, stage stopped and held; position invalid: re-home"
    $sp.Close()
    exit 1
}
finally { if ($sp.IsOpen) { $sp.Close() } }
exit 0
