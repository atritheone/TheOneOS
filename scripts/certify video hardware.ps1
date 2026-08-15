[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$EvidenceRoot,
    [string]$ExpectedDrmDriver,
    [int]$MinimumPresentedFrames = 200,
    [double]$MaximumDropPercent = 2.0,
    [double]$MaximumP95DriftMs = 50.0,
    [double]$MaximumDriftMs = 100.0
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$contractPath = Join-Path $projectRoot 'source\drivers\settings\desktop compatibility.json'
$root = [System.IO.Path]::GetFullPath($EvidenceRoot)
$telemetryPath = Join-Path $root 'graphics telemetry.json'
$playerLogPath = Join-Path $root 'player.py.log'
$mediaLogPath = Join-Path $root 'media.py.log'

foreach ($path in @($contractPath, $telemetryPath, $playerLogPath, $mediaLogPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required video certification input was not found: $path"
    }
}

$contract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
$telemetry = Get-Content -LiteralPath $telemetryPath -Raw | ConvertFrom-Json
$playerLog = Get-Content -LiteralPath $playerLogPath -Raw
$mediaLog = Get-Content -LiteralPath $mediaLogPath -Raw
$checks = [ordered]@{}
$errors = [System.Collections.Generic.List[string]]::new()

$terminal = [regex]::Matches(
    $playerLog,
    'video playback terminal state=(?<state>\w+) backend=(?<backend>[^ ]+) hardware_decode=(?<hardware>\w+) zero_copy=(?<zero>\w+) drm_driver=(?<drm>[^ ]*) va_driver=(?<va>[^ ]*) decoded_frames=(?<decoded>\d+) submitted_frames=(?<submitted>\d+) presented_frames=(?<presented>\d+) dropped_frames=(?<dropped>\d+) compositor_dropped_frames=(?<compositor_dropped>\d+) audio_underruns=(?<underruns>\d+) maximum_av_drift_ms=(?<drift>[0-9.]+) percentile_95_av_drift_ms=(?<p95>[0-9.]+)'
) | Select-Object -Last 1

$checks['terminal_telemetry'] = $null -ne $terminal

if ($null -ne $terminal) {
    $drmDriver = $terminal.Groups['drm'].Value
    $vaDriver = $terminal.Groups['va'].Value
    $backend = $terminal.Groups['backend'].Value
    $decoded = [int]$terminal.Groups['decoded'].Value
    $submitted = [int]$terminal.Groups['submitted'].Value
    $presented = [int]$terminal.Groups['presented'].Value
    $dropped = [int]$terminal.Groups['dropped'].Value
    $dropDenominator = [Math]::Max(1, $presented + $dropped)
    $dropPercent = 100.0 * $dropped / $dropDenominator

    $contractBackend = $contract.video_decode.backends |
        Where-Object { $drmDriver -in @($_.drm_drivers) } |
        Select-Object -First 1
    $allowedVaDrivers = @($contractBackend.vaapi_drivers)

    $checks['completed'] = $terminal.Groups['state'].Value -eq 'complete'
    $checks['hardware_decode'] = $terminal.Groups['hardware'].Value -eq 'True'
    $checks['zero_copy'] = $terminal.Groups['zero'].Value -eq 'True'
    $checks['drm_driver_contract'] = $null -ne $contractBackend
    $checks['va_driver_contract'] = $vaDriver -in $allowedVaDrivers
    $checks['expected_drm_driver'] = (
        [string]::IsNullOrWhiteSpace($ExpectedDrmDriver) -or
        $drmDriver -eq $ExpectedDrmDriver
    )
    $checks['hardware_backend_label'] = (
        -not [string]::IsNullOrWhiteSpace($backend) -and
        $backend -ne 'software' -and
        $backend -ne 'software-fallback'
    )
    $checks['decoded_frames'] = $decoded -ge $MinimumPresentedFrames
    $checks['submitted_frames'] = $submitted -ge $MinimumPresentedFrames
    $checks['presented_frames'] = $presented -ge $MinimumPresentedFrames
    $checks['presentation_ratio'] = (
        $submitted -gt 0 -and
        $presented -ge [Math]::Floor($submitted * 0.95)
    )
    $checks['drop_rate'] = $dropPercent -le $MaximumDropPercent
    $checks['no_compositor_drops'] = [int]$terminal.Groups['compositor_dropped'].Value -eq 0
    $checks['no_audio_underruns'] = [int]$terminal.Groups['underruns'].Value -eq 0
    $checks['maximum_av_drift'] = [double]$terminal.Groups['drift'].Value -le $MaximumDriftMs
    $checks['percentile_95_av_drift'] = [double]$terminal.Groups['p95'].Value -le $MaximumP95DriftMs
}
else {
    $drmDriver = ''
    $vaDriver = ''
    $backend = ''
    $decoded = 0
    $submitted = 0
    $presented = 0
    $dropped = 0
    $dropPercent = 100.0
}

$video = $telemetry.video_telemetry
$gpu = $telemetry.telemetry
$surfaces = $telemetry.gpu_api.video_surfaces
$checks['opengl_hardware'] = (
    [string]$telemetry.backend -eq 'opengl' -and
    [bool]$telemetry.hardware_accelerated
)
$checks['gpu_compositor'] = [string]$telemetry.window_compositor -eq 'gpu'
$checks['matching_compositor_drm_driver'] = (
    -not [string]::IsNullOrWhiteSpace($drmDriver) -and
    [string]$telemetry.drm_driver -eq $drmDriver
)
$checks['render_node'] = -not [string]::IsNullOrWhiteSpace([string]$telemetry.render_node)
$checks['dma_buf_surfaces'] = [bool]$surfaces.available -and [bool]$surfaces.zero_copy
$checks['windowserver_presented_frames'] = [int]$video.presented_frames -ge $MinimumPresentedFrames
$checks['video_partial_damage'] = [int]$video.partial_damage_frames -gt 0
$checks['video_direct_composition'] = [int]$video.direct_composition_draws -gt 0
$checks['surface_imports'] = [int]$gpu.video_surface_imports -ge $MinimumPresentedFrames
$checks['surface_draws'] = [int]$gpu.video_surface_draws -ge $MinimumPresentedFrames
$checks['surface_releases'] = [int]$gpu.video_surface_releases -ge $MinimumPresentedFrames
$checks['export_mode'] = (
    [int]$gpu.video_surface_composed_imports -gt 0 -or
    [int]$gpu.video_surface_planar_imports -gt 0
)
$checks['adaptive_gpu_scaling'] = [int]$gpu.video_surface_gpu_scaled_imports -gt 0
$checks['no_import_failures'] = [int]$gpu.video_surface_import_failures -eq 0
$checks['no_protocol_errors'] = [int]$video.protocol_errors -eq 0
$checks['no_gpu_fallbacks'] = [int]$gpu.fallbacks -eq 0 -and -not [bool]$telemetry.gpu_failed
$checks['no_software_fallback_log'] = $mediaLog -notmatch 'software-fallback'

foreach ($entry in $checks.GetEnumerator()) {
    if (-not [bool]$entry.Value) {
        $errors.Add("Check failed: $($entry.Key)")
    }
}

$report = [ordered]@{
    format = 1
    passed = $errors.Count -eq 0
    generated_at = (Get-Date).ToString('o')
    evidence_root = $root
    hardware = [ordered]@{
        drm_driver = $drmDriver
        va_driver = $vaDriver
        backend = $backend
        renderer = $telemetry.renderer
        render_node = $telemetry.render_node
    }
    playback = [ordered]@{
        decoded_frames = $decoded
        submitted_frames = $submitted
        presented_frames = $presented
        dropped_frames = $dropped
        drop_percent = [Math]::Round($dropPercent, 3)
    }
    acceptance = [ordered]@{
        minimum_presented_frames = $MinimumPresentedFrames
        maximum_drop_percent = $MaximumDropPercent
        maximum_p95_drift_ms = $MaximumP95DriftMs
        maximum_drift_ms = $MaximumDriftMs
    }
    checks = $checks
    errors = @($errors)
}
$reportPath = Join-Path $root 'video-certification-report.json'
[System.IO.File]::WriteAllText(
    $reportPath,
    ($report | ConvertTo-Json -Depth 12)
)

if (-not $report.passed) {
    throw "Video hardware certification failed. Evidence: $reportPath"
}

Write-Host "Video hardware certification passed. Evidence: $reportPath"
Write-Host ($report | ConvertTo-Json -Depth 12 -Compress)
