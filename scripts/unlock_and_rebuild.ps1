# Kill any processes that might hold locks
Get-Process -Name 'PanoFusion*','electron*' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

# Try to delete
$target = "E:\Work\PanaCamera\PanoFusion\release\win-unpacked"
if (Test-Path $target) {
    # Try rmdir first on individual locked files
    Get-ChildItem $target -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            Remove-Item $_.FullName -Force -ErrorAction Stop
        } catch {
            Write-Output "LOCKED: $($_.FullName)"
        }
    }
    # Then try removing directories
    Get-ChildItem $target -Directory -ErrorAction SilentlyContinue | Sort-Object -Property FullName -Descending | ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $target -Recurse -Force -ErrorAction SilentlyContinue
}

if (Test-Path $target) {
    Write-Output "FAILED: directory still exists"
    exit 1
} else {
    Write-Output "CLEANED"
}
