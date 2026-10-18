# Throwaway spike: capture the MuseScore main window to a PNG so the agent can look at it.
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File screenshot.ps1 <out.png>
param([Parameter(Mandatory)][string]$Out)

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class W {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
}
"@
# Without this, window coordinates are scaled on high-DPI screens and the crop is wrong.
[W]::SetProcessDPIAware() | Out-Null

$p = Get-Process MuseScore4 -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Error "MuseScore4 window not found"; exit 1 }

$r = New-Object W+RECT
[W]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$w = $r.R - $r.L; $h = $r.B - $r.T
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
# PrintWindow, not a screen copy: a screen copy grabs whatever window is on top, which may be
# unrelated to MuseScore. PW_RENDERFULLCONTENT (2) is needed for GPU-rendered Qt windows.
# The plugin's dialog is a separate window and is not in this image.
$hdc = $g.GetHdc()
$ok = [W]::PrintWindow($p.MainWindowHandle, $hdc, 2)
$g.ReleaseHdc($hdc)
if (-not $ok) { Write-Error "PrintWindow failed"; exit 1 }
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "$Out ${w}x${h}"
