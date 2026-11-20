# PowerShell 7+. Run only archives whose generator Python source you trust.
param(
    [Parameter(Mandatory=$true)][string]$InputDir,
    [string]$OutputDir = "",
    [string]$BlenderPath = "E:\blender-4.5.3-windows-x64\blender.exe",
    [switch]$Force,
    [int]$Seed = 17,
    [ValidateRange(0,1)][double]$Wear = 0.7,
    [ValidateSet(1024,2048,4096)][int]$TextureResolution = 2048,
    [string]$MaterialLibrary = "",
    [switch]$SkipRenders,
    [switch]$PrepareDayZMaps,
    [string]$ImageToPAAPath = "F:\Steam\steamapps\common\DayZ Tools\Bin\ImageToPAA\ImageToPAA.exe",
    [ValidateSet("keep","flip")][string]$NormalGreen = "keep",
    [string]$DayZPrefix = "dayz_models",
    [ValidateRange(30,7200)][int]$TimeoutSeconds = 1800
)
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7 or newer is required." }
if (-not (Test-Path -LiteralPath $BlenderPath -PathType Leaf)) { throw "Blender not found: $BlenderPath" }
if (-not (Test-Path -LiteralPath $InputDir -PathType Container)) { throw "Input folder not found: $InputDir" }
$InputDir = (Resolve-Path -LiteralPath $InputDir).Path
if (-not $OutputDir) { $OutputDir = Join-Path $InputDir "ready" }
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$OutputDir = (Resolve-Path -LiteralPath $OutputDir).Path
if (-not $MaterialLibrary) { $MaterialLibrary = Join-Path $PSScriptRoot "materials" }
$finisher = Join-Path $PSScriptRoot "DayZ_Archive_Finisher_Blender.py"
if (-not (Test-Path -LiteralPath $finisher)) { throw "Missing: $finisher" }

function Assert-OutputChild([string]$Path) {
    $resolved = [IO.Path]::GetFullPath($Path)
    $root = $OutputDir.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path outside output directory: $resolved"
    }
    return $resolved
}

function Invoke-HiddenBlender([string[]]$Arguments, [string]$WorkingDirectory, [string]$LogPath) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $BlenderPath
    $info.WorkingDirectory = $WorkingDirectory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in $Arguments) { $info.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    $started = $false
    try {
        if (-not $process.Start()) { throw "Could not start Blender" }
        $started = $true
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $clock = [Diagnostics.Stopwatch]::StartNew()
        while (-not $process.WaitForExit(250)) {
            Write-Progress -Activity "Blender" -Status ("Elapsed {0:N0} s" -f $clock.Elapsed.TotalSeconds)
            if ($clock.Elapsed.TotalSeconds -gt $TimeoutSeconds) {
                $process.Kill($true)
                $process.WaitForExit()
                throw "Blender timeout after $TimeoutSeconds seconds"
            }
        }
        if ($process.ExitCode -ne 0) { throw "Blender exited with code $($process.ExitCode). Log: $LogPath" }
    } finally {
        Write-Progress -Activity "Blender" -Completed
        if ($started) {
            if (-not $process.HasExited) { $process.Kill($true); $process.WaitForExit() }
            [IO.File]::WriteAllText($LogPath, $stdout.Result + [Environment]::NewLine + $stderr.Result)
        }
        $process.Dispose()
    }
}

$archives = @(Get-ChildItem -LiteralPath $InputDir -Filter "*.zip" -File |
    Where-Object { $_.Name -notmatch '^(DayZ_Archive_Batch_Finisher|DayZ_Finisher_2)' })
$results = [Collections.Generic.List[object]]::new()
$failed = 0
foreach ($archive in $archives) {
    $name = ($archive.BaseName -replace '[^a-zA-Z0-9_-]', '_').Trim('_')
    if (-not $name) { throw "Archive needs a usable name: $($archive.Name)" }
    $result = Assert-OutputChild (Join-Path $OutputDir $name)
    if ((Test-Path -LiteralPath $result) -and -not $Force) {
        $results.Add(@{archive=$archive.Name;status="skipped";reason="Output exists; use -Force"})
        Write-Host "Skipped: $result"
        continue
    }
    $work = Assert-OutputChild (Join-Path $OutputDir (".working_" + $name + "_" + [guid]::NewGuid().ToString("N")))
    New-Item -ItemType Directory -Path $work | Out-Null
    $backup = $null
    try {
        $extracted = Join-Path $work "source"
        Add-Type -AssemblyName System.IO.Compression
        $zip = [IO.Compression.ZipFile]::OpenRead($archive.FullName)
        try {
            foreach ($entry in $zip.Entries) {
                $entryPath = $entry.FullName.Replace([char]92,[char]47)
                if ($entryPath.StartsWith('/') -or $entryPath -match '(^|/)\.\.(/|$)' -or $entryPath -match '^[A-Za-z]:') {
                    throw "Unsafe archive entry: $entryPath"
                }
            }
        } finally { $zip.Dispose() }
        Expand-Archive -LiteralPath $archive.FullName -DestinationPath $extracted
        $scripts = @(Get-ChildItem -LiteralPath $extracted -Filter "*.py" -Recurse -File |
            Where-Object { $_.Name -match '(?i)(generator|make_|generate|create)' })
        if ($scripts.Count -gt 1) { throw "More than one generator script in $($archive.Name)" }
        if ($scripts.Count -eq 1) {
            $script = $scripts[0]
            Invoke-HiddenBlender @("--background","-t","2","--python-exit-code","1","--python",$script.FullName) $script.DirectoryName (Join-Path $work "generate.log")
        }
        $blends = @(Get-ChildItem -LiteralPath $extracted -Filter "*.blend" -Recurse -File | Sort-Object LastWriteTimeUtc -Descending)
        if (-not $blends.Count) { throw "Archive did not provide or generate a BLEND file" }
        $staged = Join-Path $work "result"
        New-Item -ItemType Directory -Path $staged | Out-Null
        $blenderArguments = @("--background","-t","2","--python-exit-code","1","--python",$finisher,"--",$blends[0].FullName,$staged,$name,
                             "--resolution",[string]$TextureResolution,"--seed",[string]$Seed,
                             "--wear",$Wear.ToString([Globalization.CultureInfo]::InvariantCulture),"--library",$MaterialLibrary)
        if ($SkipRenders) { $blenderArguments += "--no-renders" }
        if ($PrepareDayZMaps) {
            $blenderArguments += @("--dayz-converter",$ImageToPAAPath,"--normal-green",$NormalGreen,
                                   "--dayz-prefix",($DayZPrefix.TrimEnd([char[]]@(92,47)) + [char]92 + $name))
        }
        Invoke-HiddenBlender $blenderArguments $work (Join-Path $work "finish.log")
        $validation = Get-Content -LiteralPath (Join-Path $staged "validation.json") -Raw | ConvertFrom-Json
        if ($validation.status -ne "ok" -or -not $validation.glb.reimported) { throw "Validation did not confirm success" }
        if (Test-Path -LiteralPath $result) {
            if (-not $Force) { throw "Output appeared while processing; use -Force" }
            $backup = Assert-OutputChild (Join-Path $OutputDir ("_backup_" + $name + "_" + [DateTime]::UtcNow.ToString("yyyyMMdd_HHmmss_fff")))
            $null = Assert-OutputChild $result
            Move-Item -LiteralPath $result -Destination $backup
        }
        $null = Assert-OutputChild $staged
        Move-Item -LiteralPath $staged -Destination $result
        $results.Add(@{archive=$archive.Name;status="ok";output=$result;backup=$backup})
        $null = Assert-OutputChild $work
        Remove-Item -LiteralPath $work -Recurse -Force
        Write-Host "OK: $result"
    } catch {
        if ($backup -and (Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $result)) {
            $null = Assert-OutputChild $backup
            $null = Assert-OutputChild $result
            Move-Item -LiteralPath $backup -Destination $result
        }
        $results.Add(@{archive=$archive.Name;status="failed";error=$_.Exception.Message;logs=$work})
        Write-Warning $_.Exception.Message
        $failed++
    }
}
$results.ToArray() | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputDir "batch.json") -Encoding utf8
Write-Host "Finished: $($results.Count - $failed) completed/skipped, $failed failed. Output: $OutputDir"
if ($failed) { exit 1 }
