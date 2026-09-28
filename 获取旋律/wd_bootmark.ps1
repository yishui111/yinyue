param([string]$marker = "", [int]$maxage = 240)
if ($marker -and (Test-Path $marker)) {
  $age = (Get-Date) - (Get-Item $marker).LastWriteTime
  if ($age.TotalSeconds -lt $maxage) { exit 1 }
}
exit 0
