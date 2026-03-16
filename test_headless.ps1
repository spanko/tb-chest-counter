# TB Chest Counter - Local Headless Test Script

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "TB Chest Counter - Local Headless Test" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if venv exists
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "ERROR: Virtual environment not found at .venv" -ForegroundColor Red
    Write-Host "Please create it with: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

# Activate virtual environment
& ".venv\Scripts\Activate.ps1"

# Check if playwright is installed
$playwrightCheck = & python -c "import playwright" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing playwright..." -ForegroundColor Yellow
    & pip install playwright
    Write-Host "Installing Chromium browser..." -ForegroundColor Yellow
    & playwright install chromium
}

Write-Host ""
Write-Host "Running smoke test in HEADLESS mode..." -ForegroundColor Green
Write-Host "=======================================" -ForegroundColor Green

# Run the smoke test (headless by default)
& python src/main.py smoke

Write-Host ""
Write-Host "=======================================" -ForegroundColor Green
Write-Host "Headless test completed!" -ForegroundColor Green
Write-Host ""
Write-Host "Other test options:" -ForegroundColor Cyan
Write-Host "  - Visible browser:  python src/main.py smoke --visible" -ForegroundColor White
Write-Host "  - Full chest scan:  python src/main.py chests" -ForegroundColor White
Write-Host "  - Headless scan:    python src/main.py chests" -ForegroundColor White
Write-Host ""