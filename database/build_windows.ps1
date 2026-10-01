param(
    [string]$Python = (Join-Path $PSScriptRoot '.runtime\Scripts\python.exe'),
    [string]$BuildTag = 'release'
)
$ErrorActionPreference = 'Stop'
$taskBuildPath = Join-Path $PSScriptRoot "build\$BuildTag"
$taskDistPath = Join-Path $PSScriptRoot 'bin'
$taskCapturePath = Join-Path (Split-Path $PSScriptRoot -Parent) 'database_android\assets\pscube_capture.js'
New-Item -ItemType Directory -Force -Path $taskBuildPath | Out-Null
foreach ($entry in @(
    @{Name='database'; Source='app.py'},
    @{Name='database-browser'; Source='browser_import.py'},
    @{Name='database-pscube'; Source='pscube_import.py'}
)) {
    $taskBuildArgs = @('-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed',
        '--name', $entry.Name, '--distpath', $taskDistPath,
        '--workpath', $taskBuildPath, '--specpath', $taskBuildPath)
    if ($entry.Name -eq 'database-pscube') {
        $taskBuildArgs += @('--add-data', "${taskCapturePath}:database_android/assets")
    }
    $taskBuildArgs += (Join-Path $PSScriptRoot $entry.Source)
    # Windows PowerShell 5.1 は、ネイティブコマンドの標準エラー出力（PyInstallerの進行表示）を
    # エラーとして扱い、ErrorActionPreference=Stop だと成功していても止まる。終了コードで判定する。
    $taskPreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Python @taskBuildArgs *> (Join-Path $taskBuildPath "$($entry.Name).log")
    $taskExitCode = $LASTEXITCODE
    $ErrorActionPreference = $taskPreviousPreference
    if ($taskExitCode -ne 0) { throw "$($entry.Name) のビルド失敗。ログ: $taskBuildPath" }
    Write-Output "$($entry.Name): build succeeded"
}
