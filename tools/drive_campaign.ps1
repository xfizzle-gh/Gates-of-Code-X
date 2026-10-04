# Drives the running campaign app window for manual-acceptance style checks.
# Steps are strings:  "click X Y" (client-area pixels), "type TEXT", "key VK" (decimal virtual key),
# "wait SECONDS", "shot NAME" (saves build/drive/NAME.png of the app window only).
# Starts the app if it is not running. Leaves it running unless -Close is given.
param([string[]]$Steps, [switch]$Close)
$root = Split-Path $PSScriptRoot -Parent
$out = Join-Path $root 'build\drive'
New-Item -ItemType Directory -Force $out | Out-Null
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public static class WfDrive {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint f, UIntPtr e);
  public struct RECT { public int L,T,R,B; }
  public struct POINT { public int X,Y; }
}
'@
$p = Get-Process WarfighterCampaign -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $p) {
    $p = Start-Process (Join-Path $root 'build\campaign-win64\WarfighterCampaign.exe') -PassThru -ArgumentList `
        '-logFile', (Join-Path $root 'build\player-drive.log'), '-screen-fullscreen', '0', '-screen-width', '1280', '-screen-height', '720'
    Start-Sleep -Seconds 10
    $p.Refresh()
}
$h = $p.MainWindowHandle
# Never send input unless the app really is in front: a click must not land on another window.
function Focus {
    foreach ($try in 1..3) {
        # Tapping Alt lets a background process take the foreground.
        [WfDrive]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero); [WfDrive]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
        [WfDrive]::ShowWindow($h, 9) | Out-Null; [WfDrive]::SetForegroundWindow($h) | Out-Null
        Start-Sleep -Milliseconds 300
        if ([WfDrive]::GetForegroundWindow() -eq $h) { return }
    }
    throw "campaign window could not be brought to the front; no input sent"
}
foreach ($s in $Steps) {
    $a = $s -split ' ', 2
    switch ($a[0]) {
        'click' {
            $xy = $a[1] -split ' '
            $pt = New-Object WfDrive+POINT; $pt.X = [int]$xy[0]; $pt.Y = [int]$xy[1]
            Focus; [WfDrive]::ClientToScreen($h, [ref]$pt) | Out-Null
            [WfDrive]::SetCursorPos($pt.X - 2, $pt.Y) | Out-Null; Start-Sleep -Milliseconds 100
            # Real relative moves so the app's raw-input pointer state follows the cursor.
            [WfDrive]::mouse_event(1, 1, 0, 0, [UIntPtr]::Zero); Start-Sleep -Milliseconds 60
            [WfDrive]::mouse_event(1, 1, 0, 0, [UIntPtr]::Zero); Start-Sleep -Milliseconds 250
            [WfDrive]::mouse_event(2, 0, 0, 0, [UIntPtr]::Zero); Start-Sleep -Milliseconds 80
            [WfDrive]::mouse_event(4, 0, 0, 0, [UIntPtr]::Zero); Start-Sleep -Milliseconds 400
        }
        'type' { Focus; [System.Windows.Forms.SendKeys]::SendWait($a[1]); Start-Sleep -Milliseconds 300 }
        'key' { Focus; [WfDrive]::keybd_event([byte]$a[1], 0, 0, [UIntPtr]::Zero); Start-Sleep -Milliseconds 60; [WfDrive]::keybd_event([byte]$a[1], 0, 2, [UIntPtr]::Zero); Start-Sleep -Milliseconds 300 }
        'wait' { Start-Sleep -Seconds ([double]$a[1]) }
        'shot' {
            $r = New-Object WfDrive+RECT; [WfDrive]::GetWindowRect($h, [ref]$r) | Out-Null
            $bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
            $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
            [WfDrive]::PrintWindow($h, $dc, 2) | Out-Null; $g.ReleaseHdc($dc)
            $f = Join-Path $out ($a[1] + '.png'); $bmp.Save($f); $g.Dispose(); $bmp.Dispose()
            Write-Output "shot: $f"
        }
    }
}
if ($Close) { Stop-Process -Id $p.Id -Force }
