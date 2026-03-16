@echo off
echo ========================================
echo TB Chest Counter - Local Headless Test
echo ========================================
echo.

REM Check if venv exists
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found at .venv
    echo Please create it with: python -m venv .venv
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Check if playwright is installed
python -c "import playwright" 2>nul
if errorlevel 1 (
    echo Installing playwright...
    pip install playwright
    echo Installing Chromium browser...
    playwright install chromium
)

echo.
echo Running smoke test in HEADLESS mode...
echo ========================================
python src/main.py smoke

echo.
echo ========================================
echo Headless test completed!
echo.
echo To run with visible browser: python src/main.py smoke --visible
echo To run full chest scan: python src/main.py chests
pause