# Fyers stable Login Utility
# Use this script to refresh your Fyers token natively on Windows or via WSL (powershell.exe).

$ErrorActionPreference = "Stop"

$envPath = Join-Path $PSScriptRoot ".env"
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        if ($_ -match '^([^=]+)=(.+)$') {
            $key = $Matches[1].Trim()
            $val = $Matches[2].Trim()
            Set-Variable -Name ("ENV_" + $key) -Value $val -Force -ErrorAction SilentlyContinue
        }
    }
}

$clientId = $ENV_FYERS_CLIENT_ID
$secretId = $ENV_FYERS_SECRET_ID
$redirectUri = "https://trade.fyers.in/api-login/redirect-url"

if (-not $clientId -or -not $secretId) {
    Write-Host "Error: FYERS_CLIENT_ID or FYERS_SECRET_ID not found in .env" -ForegroundColor Red
    $clientId = Read-Host "Please enter your Fyers Client ID"
    $secretId = Read-Host "Please enter your Fyers Secret ID"
}

$escapedUri = [uri]::EscapeDataString($redirectUri)
$authUrl = "https://api-t1.fyers.in/api/v3/generate-authcode?client_id=" + $clientId + "&redirect_uri=" + $escapedUri + "&response_type=code&state=None"

Write-Host ""
Write-Host "Fyers Authentication required" -ForegroundColor Cyan
Write-Host "1. Open this URL in your browser:"
Write-Host $authUrl -ForegroundColor Yellow
Write-Host ""
Write-Host "2. Login and you will be redirected to a page."
Write-Host "3. Copy the FULL URL of that page and paste it below."

$fullUrl = Read-Host "Paste the Redirected URL here"

$authCode = ""
if ($fullUrl -match 'auth_code=([^&]+)') {
    $authCode = $Matches[1]
}
else {
    $authCode = $fullUrl.Trim()
}

Write-Host ""
Write-Host "Exchanging auth code for access token..." -ForegroundColor Cyan

# Calculate AppIdHash (SHA256 of ClientID:SecretID)
$stringToHash = $clientId + ":" + $secretId
$sha256 = [System.Security.Cryptography.SHA256]::Create()
$hashBytes = $sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($stringToHash))
$appIdHash = [System.BitConverter]::ToString($hashBytes).Replace("-" , "").ToLower()

$bodyObj = @{
    grant_type = "authorization_code"
    appIdHash  = $appIdHash
    code       = $authCode
}
$bodyJson = $bodyObj | ConvertTo-Json

try {
    # Using the correct /validate-authcode endpoint found during debug
    $response = Invoke-RestMethod -Method Post -Uri "https://api-t1.fyers.in/api/v3/validate-authcode" -Body $bodyJson -ContentType "application/json"
    
    if ($response.s -eq "ok") {
        $accessToken = $response.access_token
        
        # Calculate Expiry (Tomorrow 6 AM)
        $expiryDate = (Get-Date).AddDays(1).Date.AddHours(6)
        $expiryTimestamp = [int][double]::Parse((New-TimeSpan -Start (Get-Date -Date "1970-01-01") -End $expiryDate).TotalSeconds)
        
        $tokenData = @{
            access_token    = $accessToken
            expiry          = $expiryTimestamp
            expiry_readable = $expiryDate.ToString("yyyy-MM-dd HH:mm:ss")
        } | ConvertTo-Json
        
        $tokenFile = Join-Path $PSScriptRoot "fyers_token.json"
        Set-Content -Path $tokenFile -Value $tokenData -Encoding utf8
        
        Write-Host ""
        Write-Host "Token successfully saved to fyers_token.json!" -ForegroundColor Green
        Write-Host "Bot is now ready." -ForegroundColor Green
    }
    else {
        Write-Host ""
        Write-Host "Authentication Failed: " -NoNewline -ForegroundColor Red
        Write-Host $response.message
    }
}
catch {
    Write-Host ""
    Write-Host "Error during token exchange:" -ForegroundColor Red
    Write-Host $_.Exception.Message
}

Write-Host ""
Write-Host "Press Enter to exit..."
[void][System.Console]::ReadLine()
