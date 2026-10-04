# Builds the campaign application from campaign/ into build/campaign-win64.
param(
    [string]$Unity = 'C:\Program Files\Unity\Hub\Editor\6000.6.4f1\Editor\Unity.exe'
)
$root = Split-Path $PSScriptRoot -Parent
$editorDir = Join-Path $root 'campaign\Assets\Editor'
New-Item -ItemType Directory -Force $editorDir | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'unity\WfBuild.cs') $editorDir -Force
$log = Join-Path $root 'build\unity-build.log'
& $Unity -batchmode -projectPath (Join-Path $root 'campaign') -executeMethod WfBuild.BuildWindows -logFile $log | Out-Null
$code = $LASTEXITCODE
Select-String -Path $log -Pattern 'WfBuild|error CS\d+|Build Finished|Error building' | Select-Object -First 30 | ForEach-Object { $_.Line }
exit $code
