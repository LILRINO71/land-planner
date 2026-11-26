# Land Planner: install or update on Windows. No administrator rights, no Python needed.
#
#   irm https://raw.githubusercontent.com/LILRINO71/land-planner/main/install.ps1 | iex
#
# It downloads the latest release, puts it in %LOCALAPPDATA%\LandPlanner, adds "Land Planner" to the Desktop and
# the Start menu, and starts it. Running it again updates the app; your saved lands and plans (the data folder)
# are kept. To remove Land Planner, delete that folder and the two shortcuts.
#
# For testing: LANDPLANNER_DIR (where to install), LANDPLANNER_ZIP (a local zip or another address),
# LANDPLANNER_NO_SHORTCUT=1, LANDPLANNER_NO_START=1.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repo = "LILRINO71/land-planner"
$source = if ($env:LANDPLANNER_ZIP) { $env:LANDPLANNER_ZIP } else { "https://github.com/$repo/releases/latest/download/LandPlanner.zip" }
$dir = if ($env:LANDPLANNER_DIR) { $env:LANDPLANNER_DIR } else { Join-Path $env:LOCALAPPDATA "LandPlanner" }
$starter = Join-Path $dir "Start Land Planner.bat"

Write-Host ""
Write-Host "  Land Planner" -ForegroundColor Green
Write-Host "  Installing to $dir"

$work = Join-Path ([IO.Path]::GetTempPath()) ("landplanner-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $zip = Join-Path $work "LandPlanner.zip"
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $zip
    } else {
        Write-Host "  Downloading (about 11 MB)..."
        Invoke-WebRequest -Uri $source -OutFile $zip -UseBasicParsing
    }
    Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $work "new")
    $new = Join-Path $work "new\LandPlanner"
    if (-not (Test-Path -LiteralPath (Join-Path $new "runtime\python.exe")) -or -not (Test-Path -LiteralPath (Join-Path $new "landplanner"))) {
        throw "The download is not a complete copy of Land Planner. Try again in a minute."
    }

    # An older copy that is running would keep its files locked: stop it first.
    if (Test-Path -LiteralPath $dir) {
        $mine = (Resolve-Path -LiteralPath $dir).Path
        Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($mine, [StringComparison]::OrdinalIgnoreCase) } |
            Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 600
    }
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    # Everything is replaced except the data folder: My lands, plans and saved answers stay.
    Get-ChildItem -LiteralPath $dir -Force | Where-Object { $_.Name -ne "data" } | Remove-Item -Recurse -Force
    Copy-Item -Path (Join-Path $new "*") -Destination $dir -Recurse -Force
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $env:LANDPLANNER_NO_SHORTCUT) {
    $shell = New-Object -ComObject WScript.Shell
    $places = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
    foreach ($place in $places) {
        if (-not $place) { continue }
        $link = $shell.CreateShortcut((Join-Path $place "Land Planner.lnk"))
        $link.TargetPath = $starter
        $link.WorkingDirectory = $dir
        $link.Description = "Land Planner: large parcels of land, and how each could be divided"
        $icon = Join-Path $dir "landplanner.ico"
        if (Test-Path -LiteralPath $icon) { $link.IconLocation = $icon }
        $link.WindowStyle = 7   # start with its window minimised; the app itself opens in the browser
        $link.Save()
    }
    Write-Host "  Added 'Land Planner' to the Desktop and the Start menu."
}

$version = ""
$versionFile = Join-Path $dir "VERSION.txt"
if (Test-Path -LiteralPath $versionFile) { $version = (Get-Content -LiteralPath $versionFile -TotalCount 1).Trim() }
Write-Host "  Installed $version" -ForegroundColor Green
Write-Host "  Your saved lands and plans are kept in $(Join-Path $dir 'data') on this computer only."

if (-not $env:LANDPLANNER_NO_START) {
    Write-Host "  Starting Land Planner. It opens in your browser."
    Start-Process -FilePath $starter -WorkingDirectory $dir -WindowStyle Minimized
}
Write-Host ""
