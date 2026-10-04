# Launches the built campaign app windowed, captures its own window (not the desktop), closes it,
# and reports exceptions from the player log.
param([int]$Seconds = 15)
$root = Split-Path $PSScriptRoot -Parent
$log = Join-Path $root 'build\player-smoke.log'
$png = Join-Path $root 'build\player-smoke.png'
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public static class WfWinCap {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  public struct RECT { public int L,T,R,B; }
}
'@
$p = Start-Process (Join-Path $root 'build\campaign-win64\WarfighterCampaign.exe') -PassThru -ArgumentList `
    '-logFile', $log, '-screen-fullscreen', '0', '-screen-width', '1280', '-screen-height', '720'
Wait-Process -Id $p.Id -Timeout $Seconds -ErrorAction SilentlyContinue
if ($p.HasExited) { Write-Output "exited early with code $($p.ExitCode)"; exit 1 }
$p.Refresh()
$r = New-Object WfWinCap+RECT
[WfWinCap]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc(); [WfWinCap]::PrintWindow($p.MainWindowHandle, $dc, 2) | Out-Null; $g.ReleaseHdc($dc)
$bmp.Save($png); $g.Dispose(); $bmp.Dispose()
Stop-Process -Id $p.Id -Force
$n = (Select-String -Path $log -Pattern 'Exception').Count
Write-Output "screenshot: $png"
Write-Output "exceptions in log: $n"
exit ([int]($n -gt 0))
