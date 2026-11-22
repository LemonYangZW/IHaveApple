# 打包 Windows 版：编译 ohgd + PyInstaller 打包播放器，汇总成 dist/IHaveApple，再压成 zip。
# 需要 Go、Python（已装 prototype/requirements.txt 和 pyinstaller）、pwsh。
#
#   pwsh scripts/build-windows.ps1 -Version v0.1.0 -Mpv path/to/libmpv-2.dll -Ffmpeg path/to/ffmpeg.exe
param(
    [string]$Version = "dev",
    [Parameter(Mandatory)] [string]$Mpv,
    [Parameter(Mandatory)] [string]$Ffmpeg
)
$ErrorActionPreference = "Stop"
$Root  = Split-Path -Parent $PSScriptRoot
$Proto = Join-Path $Root "prototype"
$Dist  = Join-Path $Root "dist"
$Out   = Join-Path $Dist "IHaveApple"
$Mpv    = (Resolve-Path $Mpv).Path
$Ffmpeg = (Resolve-Path $Ffmpeg).Path

if (Test-Path $Dist) { Remove-Item $Dist -Recurse -Force }

Write-Host "== 1/3 PyInstaller 打包播放器 =="
# --specpath 设在 build/ 下，--add-data 一律用绝对路径
python -m PyInstaller --noconfirm --windowed --name IHaveApple `
    --distpath $Dist --workpath (Join-Path $Root "build") --specpath (Join-Path $Root "build") `
    --add-data "$Proto/qml;qml" `
    --add-data "$Proto/fonts;fonts" `
    --add-data "$Proto/assets;assets" `
    --add-data "$Mpv;lib" `
    (Join-Path $Proto "main.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败" }

Write-Host "== 2/3 编译 ohgd =="
$Hgd = Join-Path $Out "hgd"
New-Item -ItemType Directory -Force $Hgd | Out-Null
Push-Location (Join-Path $Root "sdk/hgd")
try {
    go build -trimpath -ldflags "-s -w" -o (Join-Path $Hgd "ohgd.exe") .
    if ($LASTEXITCODE -ne 0) { throw "go build 失败" }
} finally { Pop-Location }
Copy-Item (Join-Path $Root "sdk/hgd/config.example.json") (Join-Path $Hgd "config.json")

Write-Host "== 3/3 汇总 =="
$FfDir = Join-Path $Out "ffmpeg"
New-Item -ItemType Directory -Force $FfDir | Out-Null
Copy-Item $Ffmpeg (Join-Path $FfDir "ffmpeg.exe")
Copy-Item (Join-Path $Root "README.md") $Out
Copy-Item (Join-Path $Root "sdk/openhongguo/LICENSE") (Join-Path $Out "LICENSE-openhongguo.txt")

$Zip = Join-Path $Dist "IHaveApple-$Version-win64.zip"
Compress-Archive -Path $Out -DestinationPath $Zip
Write-Host "完成：$Zip"
