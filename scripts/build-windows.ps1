# 打包 Windows 版：PyInstaller 打包播放器 + 编译 ohgd，汇总成 dist/IHaveApple，再用 Inno Setup 生成安装包。
# 需要 Go、Python（已装 prototype/requirements.txt 和 pyinstaller）、pwsh、Inno Setup 6.3+（ISCC）。
#
#   pwsh scripts/build-windows.ps1 -Version v0.1.2 -Mpv path/to/libmpv-2.dll -Ffmpeg path/to/ffmpeg.exe
#
# -Iscc 可选：不传时依次找 PATH、Program Files、scoop 安装的 Inno Setup。
param(
    [string]$Version = "dev",
    [Parameter(Mandatory)] [string]$Mpv,
    [Parameter(Mandatory)] [string]$Ffmpeg,
    [string]$Iscc = ""
)
$ErrorActionPreference = "Stop"
$Root  = Split-Path -Parent $PSScriptRoot
$Proto = Join-Path $Root "prototype"
$Dist  = Join-Path $Root "dist"
$Out   = Join-Path $Dist "IHaveApple"
$Mpv    = (Resolve-Path $Mpv).Path
$Ffmpeg = (Resolve-Path $Ffmpeg).Path

function Find-Iscc([string]$Hint) {
    if ($Hint) {
        if (-not (Test-Path $Hint)) { throw "找不到 ISCC.exe：$Hint" }
        return (Resolve-Path $Hint).Path
    }
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) {
        # scoop 的 shim 旁边没有 Languages 目录，回到真实安装目录
        if (-not (Test-Path (Join-Path (Split-Path $cmd.Source -Parent) "Languages"))) {
            $prefix = & scoop prefix inno-setup 2>$null
            if ($LASTEXITCODE -eq 0 -and $prefix -and (Test-Path (Join-Path $prefix "ISCC.exe"))) {
                return (Join-Path $prefix "ISCC.exe")
            }
        }
        return $cmd.Source
    }
    $x86 = [Environment]::GetFolderPath("ProgramFilesX86")
    $candidates = @(
        (Join-Path $x86 "Inno Setup 7\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 7\ISCC.exe"),
        (Join-Path $x86 "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    throw "找不到 ISCC.exe：请安装 Inno Setup（scoop install extras/inno-setup 或 choco install innosetup），或用 -Iscc 指定路径"
}

if (Test-Path $Dist) { Remove-Item $Dist -Recurse -Force }

Write-Host "== 1/4 PyInstaller 打包播放器 =="
# --specpath 设在 build/ 下，--add-data 一律用绝对路径
$PyArgs = @(
    "-m", "PyInstaller", "--noconfirm", "--windowed", "--name", "IHaveApple",
    "--icon", (Join-Path $Root "packaging/app.ico"),
    "--distpath", $Dist,
    "--workpath", (Join-Path $Root "build"),
    "--specpath", (Join-Path $Root "build"),
    "--add-data", "$Proto/qml;qml",
    "--add-data", "$Proto/fonts;fonts",
    "--add-data", "$Proto/assets;assets",
    "--add-data", "$Mpv;lib",
    (Join-Path $Proto "main.py")
)
python @PyArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败" }

Write-Host "== 2/4 编译 ohgd =="
$Hgd = Join-Path $Out "hgd"
New-Item -ItemType Directory -Force $Hgd | Out-Null
Push-Location (Join-Path $Root "sdk/hgd")
try {
    go build -trimpath -ldflags "-s -w" -o (Join-Path $Hgd "ohgd.exe") .
    if ($LASTEXITCODE -ne 0) { throw "go build 失败" }
} finally { Pop-Location }
Copy-Item (Join-Path $Root "sdk/hgd/config.example.json") (Join-Path $Hgd "config.json")
$Cfg = Get-Content (Join-Path $Hgd "config.json") -Raw | ConvertFrom-Json
if ($Cfg.signer_url) {
    throw "打包版必须使用内置签名：请把 sdk/hgd/config.example.json 的 signer_url 留空（当前为 $($Cfg.signer_url)）"
}

Write-Host "== 3/4 汇总 =="
$FfDir = Join-Path $Out "ffmpeg"
New-Item -ItemType Directory -Force $FfDir | Out-Null
Copy-Item $Ffmpeg (Join-Path $FfDir "ffmpeg.exe")
Copy-Item (Join-Path $Root "README.md") $Out
Copy-Item (Join-Path $Root "sdk/openhongguo/LICENSE") (Join-Path $Out "LICENSE-openhongguo.txt")

Write-Host "== 4/4 生成安装包 =="
$Iscc = Find-Iscc $Iscc
$VerNum = $Version -replace '^[vV]', ''
if ($VerNum -notmatch '^\d+(\.\d+){0,3}$') { $VerNum = "0.0.0" }
$VerParts = @($VerNum -split '[.]')
while ($VerParts.Count -lt 4) { $VerParts += "0" }
$VerNum4 = $VerParts -join '.'
$Defines = @("/DAppVersion=$VerNum", "/DAppVersion4=$VerNum4", "/DAppTag=$Version")
$LangFile = Join-Path (Split-Path $Iscc -Parent) "Languages\ChineseSimplified.isl"
if (Test-Path $LangFile) {
    $Defines += "/DUseChinese"
} else {
    Write-Host "提示：当前 Inno Setup 没有中文语言文件，安装向导用英文"
}
& $Iscc @Defines (Join-Path $Root "packaging/IHaveApple.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup 失败" }

$Setup = Join-Path $Dist "IHaveApple-Setup-$Version-win64.exe"
if (-not (Test-Path $Setup)) { throw "没有生成安装包：$Setup" }
$Size = [math]::Round((Get-Item $Setup).Length / 1MB, 1)
Write-Host "完成：$Setup（$Size MB）"
