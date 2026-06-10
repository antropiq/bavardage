# Start the transcription server and open browser
$ErrorActionPreference = "Stop"

$venv = ".venv\Scripts\python.exe"
$server = "src\server.py"
$url = "http://localhost:8765"
$serverProcess = $null
$browserProcess = $null

# Cleanup handler
$onExit = {
    if ($browserProcess -and -not $browserProcess.HasExited) {
        Write-Host "`nClosing browser..." -ForegroundColor Yellow
        try {
            Stop-Process -Id $browserProcess.Id -Force -ErrorAction SilentlyContinue
        } catch {}
    }
    if ($serverProcess -and -not $serverProcess.HasExited) {
        Write-Host "Stopping server..." -ForegroundColor Yellow
        try {
            Stop-Process -Id $serverProcess.Id -ErrorAction Stop
            $serverProcess.WaitForExit(5000)
        } catch {}
    }
}

# Trap Ctrl+C
trap {
    & $onExit
    exit 0
}

Write-Host "Checking Python environment..." -ForegroundColor Cyan
if (-not (Test-Path $venv)) {
    Write-Host "ERROR: Virtual environment not found at $venv" -ForegroundColor Red
    Write-Host "Run: .venv\Scripts\activate" -ForegroundColor Yellow
    exit 1
}

Write-Host "Starting transcription server..." -ForegroundColor Cyan
$serverProcess = Start-Process -FilePath $venv -ArgumentList $server -PassThru

Write-Host "Waiting for server to be ready..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $result = $tcp.BeginConnect("localhost", 8765, $null, $null)
        $wait = $result.AsyncWaitHandle.WaitOne(500, $false)
        if ($wait) {
            $tcp.EndConnect($result)
            $tcp.Close()
            $ready = $true
            break
        }
        $tcp.Close()
    } catch {}
    Start-Sleep -Milliseconds 500
}

if ($ready) {
    Write-Host "Server ready! Opening browser..." -ForegroundColor Green
} else {
    Write-Host "Server started (model still loading). Opening browser..." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Opening $url ..." -ForegroundColor Cyan
$browserProcess = Start-Process $url -PassThru
Start-Sleep -Seconds 1

Write-Host "Press Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host ""

# Keep script alive
while ($true) { Start-Sleep -Seconds 1 }
