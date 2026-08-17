# T1OS incremental runtime test dispatcher.

[CmdletBinding()]
param(
    [switch]$GraphicsBaseline,
    [switch]$UpdateGraphicsBaseline,
    [switch]$GraphicsOpenGL,
    [switch]$GraphicsCompositor,
    [switch]$GraphicsBrick,
    [switch]$GraphicsPlayer,
    [switch]$BrickDirectives,
    [switch]$GraphicsWrite,
    [switch]$WritePerformance,
    [switch]$GraphicsArray,
    [switch]$GraphicsCalculator,
    [switch]$GraphicsOperationsCentre,
    [switch]$OperationsServer,
    [switch]$GraphicsExpanse,
    [switch]$GraphicsStartup,
    [switch]$GraphicsLockscreen,
    [switch]$GraphicsBoot,
    [switch]$VirtualBoxClipboard,
    [switch]$GraphicsKms,
    [switch]$Audio,
    [switch]$Media,
    [switch]$Image,
    [switch]$OpenGL,
    [switch]$Deployed
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot 'incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}

$ErrorActionPreference = 'Stop'
$caseRoot = Join-Path $PSScriptRoot 'tests\runtime'
$case = $null
$caseArguments = @()

if ($GraphicsBaseline -or $UpdateGraphicsBaseline -or $GraphicsOpenGL -or $GraphicsCompositor -or $GraphicsBrick -or $GraphicsPlayer -or $BrickDirectives -or $GraphicsWrite -or $WritePerformance -or $GraphicsArray -or $GraphicsCalculator -or $GraphicsOperationsCentre -or $OperationsServer -or $GraphicsExpanse -or $GraphicsStartup -or $GraphicsLockscreen -or $GraphicsBoot -or $VirtualBoxClipboard) {
    $mode = if ($VirtualBoxClipboard) { 'virtualbox-clipboard' } elseif ($GraphicsBoot) { 'boot' } elseif ($GraphicsLockscreen) { 'lockscreen' } elseif ($GraphicsStartup) { 'startup' } elseif ($GraphicsExpanse) { 'expanse' } elseif ($OperationsServer) { 'operations-server' } elseif ($GraphicsOperationsCentre) { 'operations-centre' } elseif ($GraphicsCalculator) { 'calculator' } elseif ($GraphicsArray) { 'array' } elseif ($WritePerformance) { 'write-performance' } elseif ($GraphicsWrite) { 'write' } elseif ($BrickDirectives) { 'brick-directives' } elseif ($GraphicsPlayer) { 'player' } elseif ($GraphicsBrick) { 'brick' } elseif ($GraphicsCompositor) { 'compositor' } elseif ($GraphicsOpenGL) { 'opengl' } else { 'baseline' }
    $case = 'graphics.ps1'
    $caseArguments = @('-Mode', $mode)
    if ($UpdateGraphicsBaseline) { $caseArguments += '-Update' }
    if ($Deployed) { $caseArguments += '-Deployed' }
}
elseif ($GraphicsKms) {
    $case = 'kms.ps1'
}
elseif ($Audio -or $Media) {
    $case = 'audio.ps1'
}
elseif ($Image) {
    $case = 'image.ps1'
}
else {
    $case = 'qemu.ps1'
    if ($OpenGL) { $caseArguments += '-OpenGL' }
}

$casePath = Join-Path $caseRoot $case
if (-not (Test-Path -LiteralPath $casePath -PathType Leaf)) {
    throw "Required runtime validation case not found: $casePath"
}
& pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $casePath @caseArguments
if ($LASTEXITCODE -ne 0) {
    throw "Runtime validation case failed: $case"
}
