# Stock AI Beast - One-Click Launcher
# Purpose: Setup environment, check data, and launch trading modes.

$ErrorActionPreference = "Stop"

function Print-Header {
    param($title)
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "   $title" -ForegroundColor White
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Check-WSL {
    Print-Header "1. SYSTEM CHECK"
    if (-not (Get-Command "wsl" -ErrorAction SilentlyContinue)) {
        Write-Host "❌ WSL (Windows Subsystem for Linux) is not installed or not in PATH." -ForegroundColor Red
        Read-Host "Press Enter to exit..."
        exit
    }
    Write-Host "✅ WSL is available." -ForegroundColor Green
}

function Check-Token {
    Print-Header "2. AUTH CHECK"
    $tokenPath = Join-Path $PSScriptRoot "fyers_token.json"
    $needsLogin = $true

    if (Test-Path $tokenPath) {
        try {
            $json = Get-Content $tokenPath -Raw | ConvertFrom-Json
            $expiry = [math]::Round($json.expiry)
            $now = [int][double]::Parse((New-TimeSpan -Start (Get-Date -Date "1970-01-01") -End (Get-Date)).TotalSeconds)
            
            if ($expiry -gt $now) {
                $hoursLeft = [math]::Round(($expiry - $now) / 3600, 1)
                Write-Host "✅ Valid Token Found (Expires in $hoursLeft hours)" -ForegroundColor Green
                $needsLogin = $false
            }
            else {
                Write-Host "⚠️ Token Expired." -ForegroundColor Yellow
            }
        }
        catch {
            Write-Host "⚠️ Token file is corrupt." -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "⚠️ No token found." -ForegroundColor Yellow
    }

    if ($needsLogin) {
        Write-Host "🔄 Initiating Login Flow..." -ForegroundColor Cyan
        & "$PSScriptRoot\fyers_login.ps1"
    }
}

function Check-Data {
    Print-Header "3. DATA INTEGRITY"
    Write-Host "⏳ Checking for data gaps in WSL... (This may take a moment)" -ForegroundColor Gray
    
    # Run the python script inside WSL to leverage existing environment
    wsl cd "/home/beast/projects/stock-ai-beast" "&&" .venv/bin/python data/check_and_fill.py
}

function Start-Services {
    Print-Header "4. INFRASTRUCTURE"
    Write-Host "🐳 Starting Docker Services (Dashboard, Redis, Brain)..." -ForegroundColor Gray
    
    # Smart Check: Verify if containers are already running
    $runningContainers = docker ps --format "{{.Names}}"
    $services = @("beast_brain", "beast_redis", "stock-ai-beast-frontend-1", "stock-ai-beast-backend-1")
    $allRunning = $true
    
    foreach ($svc in $services) {
        if ($runningContainers -notmatch $svc) {
            $allRunning = $false
            break
        }
    }
    
    if ($allRunning) {
        Write-Host "   ✅ Docker services are already active." -ForegroundColor Green
        $action = Read-Host "   [C]ontinue with existing or [R]estart all? (Default: Continue)"
        
        if ($action -match "^[rR]") {
            Write-Host "   🔄 Restarting Services..." -ForegroundColor Cyan
            docker compose -f docker-compose.dashboard.yml -f docker-compose.llm.yml down
            docker compose -f docker-compose.dashboard.yml -f docker-compose.llm.yml up -d
        }
        else {
            Write-Host "   ➡  Using existing services." -ForegroundColor Gray
        }
    }
    else {
        Write-Host "   🚀 Starting Services..." -ForegroundColor Cyan
        docker compose -f docker-compose.dashboard.yml -f docker-compose.llm.yml up -d
    }
    
    # Check Brain
    Start-Sleep -Seconds 2
    $brainStatus = docker inspect -f '{{.State.Health.Status}}' beast_brain 2>$null
    if ($brainStatus -eq 'healthy') {
        Write-Host "✅ Brain is HEALTHY." -ForegroundColor Green
    }
    else {
        Write-Host "⏳ Brain is starting up... (Status: $brainStatus)" -ForegroundColor Yellow
    }
    
    Write-Host ""
    Write-Host "📊 Dashboard available at: http://localhost:3000" -ForegroundColor Cyan

    # Start Option Chain Recorder (Background)
    Write-Host ""
    Write-Host "📡 Initializing NIFTY Option Chain Recorder..." -ForegroundColor Gray
    # Run in detached (background) mode using Start-Process to keep it independent
    # Using wsl directly to launch python in venv
    Start-Process wsl -ArgumentList "cd /home/beast/projects/stock-ai-beast && .venv/bin/python data/record_options.py >> logs/recorder.log 2>&1" -WindowStyle Hidden
    Write-Host "   ✅ Recorder started (Check logs/recorder.log)" -ForegroundColor Green
}

function Show-Menu {
    Print-Header "5. COMMAND CENTER"
    Write-Host "Choose an action:"
    Write-Host " [1] [TEST] Run Backtest Analysis (Latest Session)"
    Write-Host " [2] [MOCK] Start MOCK Trading (Strict Simulation)"
    Write-Host " [3] [LIVE] Start LIVE Trading (Real Money)"
    Write-Host " [4] [LOGS] View Engine Logs"
    Write-Host " [5] [EXIT] Exit"
    Write-Host ""
    
    $choice = Read-Host "Enter your choice [1-5]"
    
    switch ($choice) {
        "1" { 
            Write-Host "🚀 Running Backtest Analysis..." -ForegroundColor Cyan
            wsl cd "/home/beast/projects/stock-ai-beast" "&&" .venv/bin/python analyze_trades.py
            Read-Host "Press Enter to return to menu..."
            Show-Menu
        }
        "2" {
            Write-Host "🚀 Starting MOCK Trading Engine..." -ForegroundColor Cyan
            Write-Host "   (Press Ctrl+C to stop)" -ForegroundColor Gray
            docker exec -it beast_engine python -u -m engine.live_engine --simulation
            Show-Menu
        }
        "3" {
            Write-Host "⚠️ STARTING LIVE TRADING..." -ForegroundColor Red
            $confirm = Read-Host "Type 'LIVE' to confirm real money trading"
            if ($confirm -eq 'LIVE') {
                docker exec -it beast_engine python -u -m engine.live_engine --live-exec
            }
            else {
                Write-Host "❌ Aborted." -ForegroundColor Red
            }
            Show-Menu
        }
        "4" {
            docker logs -f beast_engine
            Show-Menu
        }
        "5" { exit }
        Default { Show-Menu }
    }
}

# Main Execution Flow
Check-WSL
Check-Token
Check-Data
Start-Services
Show-Menu
