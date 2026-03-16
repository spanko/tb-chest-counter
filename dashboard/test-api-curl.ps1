# PowerShell script to test the admin API endpoints

$API_BASE = "https://tb-chest-for.azurestaticapps.net/api"
$ADMIN_CODE = "FOR2026-ADMIN"

Write-Host "=== Testing Admin API Endpoints ===" -ForegroundColor Cyan
Write-Host ""

# Test Health Endpoint
Write-Host "1. Testing Health Endpoint..." -ForegroundColor Yellow
$healthResponse = Invoke-WebRequest -Uri "$API_BASE/admin?action=health" `
    -Headers @{"X-Admin-Code"=$ADMIN_CODE} `
    -Method GET `
    -UseBasicParsing `
    -ErrorAction SilentlyContinue

if ($healthResponse) {
    Write-Host "Status: $($healthResponse.StatusCode)" -ForegroundColor Green
    Write-Host "Response:" -ForegroundColor White
    $healthResponse.Content | ConvertFrom-Json | ConvertTo-Json -Depth 10
} else {
    Write-Host "Failed to get response" -ForegroundColor Red
}

Write-Host ""
Write-Host "2. Testing Status Endpoint..." -ForegroundColor Yellow
$statusResponse = Invoke-WebRequest -Uri "$API_BASE/admin?action=status" `
    -Headers @{"X-Admin-Code"=$ADMIN_CODE} `
    -Method GET `
    -UseBasicParsing `
    -ErrorAction SilentlyContinue

if ($statusResponse) {
    Write-Host "Status: $($statusResponse.StatusCode)" -ForegroundColor Green
    Write-Host "Response (first 500 chars):" -ForegroundColor White
    $content = $statusResponse.Content
    if ($content.Length -gt 500) {
        Write-Host $content.Substring(0, 500) "..."
    } else {
        Write-Host $content
    }
} else {
    Write-Host "Failed to get response" -ForegroundColor Red
}

Write-Host ""
Write-Host "3. Testing Trigger Endpoint..." -ForegroundColor Yellow
$body = @{
    jobName = "tbdev-scan-for-main"
    resourceGroup = "rg-tb-chest-counter-dev"
} | ConvertTo-Json

$triggerResponse = Invoke-WebRequest -Uri "$API_BASE/admin?action=trigger" `
    -Headers @{"X-Admin-Code"=$ADMIN_CODE; "Content-Type"="application/json"} `
    -Method POST `
    -Body $body `
    -UseBasicParsing `
    -ErrorAction SilentlyContinue

if ($triggerResponse) {
    Write-Host "Status: $($triggerResponse.StatusCode)" -ForegroundColor Green
    Write-Host "Response:" -ForegroundColor White
    $triggerResponse.Content | ConvertFrom-Json | ConvertTo-Json -Depth 10
} else {
    Write-Host "Failed to get response" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Test Complete ===" -ForegroundColor Cyan