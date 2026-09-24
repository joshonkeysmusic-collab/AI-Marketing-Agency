# Renders the week's visual assets from HTML using headless Chrome.
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$src = $PSScriptRoot
$out = Split-Path $src -Parent
$profile = Join-Path $env:TEMP "li-asset-render"

$pngs = @{
  "a1-whatsapp-crm.html"  = "2026-09-28-whatsapp-crm.png"
  "a2-pipeline.html"      = "2026-09-29-pipeline-diagram.png"
  "a4-approval-gate.html" = "2026-10-01-approval-gate.png"
}
foreach ($k in $pngs.Keys) {
  $url = "file:///" + ((Join-Path $src $k) -replace '\\','/')
  & $chrome --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$profile" --window-size=1080,1350 --virtual-time-budget=8000 --screenshot="$(Join-Path $out $pngs[$k])" $url 2>$null | Out-Null
}
$url = "file:///" + ((Join-Path $src "a3-carousel.html") -replace '\\','/')
& $chrome --headless=new --disable-gpu --user-data-dir="$profile" --no-pdf-header-footer --virtual-time-budget=8000 --print-to-pdf="$(Join-Path $out '2026-09-30-manual-work-cost.pdf')" $url 2>$null | Out-Null
Get-ChildItem $out -File | Where-Object { $_.Extension -in '.png','.pdf' } | Select-Object Name, Length
