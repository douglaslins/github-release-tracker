@echo off
setlocal
cd /d "%~dp0"
echo Building GitHubReleaseTracker.exe (portable, single file)...
where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% --version
if errorlevel 1 (
  echo.
  echo Python was not found. Install Python 3 from python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
%PY% -m pip install --upgrade pyinstaller
if errorlevel 1 (
  echo.
  echo Could not install PyInstaller. Check your internet connection.
  pause
  exit /b 1
)
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name GitHubReleaseTracker github_release_tracker.py
if errorlevel 1 (
  echo.
  echo Build failed. See the messages above.
  pause
  exit /b 1
)
echo.
echo Done. Your portable app is: %~dp0dist\GitHubReleaseTracker.exe
echo Copy that single file anywhere. It keeps projects.json next to itself.
pause