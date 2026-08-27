@echo off
setlocal
cd /d "%~dp0"

set "PORT=8765"
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo.
  echo   找不到虚拟环境 / Virtual environment not found:
  echo     %CD%\%PY%
  echo.
  echo   请先执行 / Run these first:
  echo     py -3.12 -m venv .venv
  echo     .venv\Scripts\python.exe -m pip install -e ".[dev,api]"
  echo.
  pause
  exit /b 1
)

echo.
echo   Proteus - http://127.0.0.1:%PORT%/
echo   关闭此窗口即停止服务 / Close this window to stop the server.
echo.

start "" "http://127.0.0.1:%PORT%/"
"%PY%" -m proteus api --port %PORT%

if errorlevel 1 (
  echo.
  echo   服务异常退出 / The server exited with an error.
  echo   端口 %PORT% 可能已被占用 / Port %PORT% may already be in use.
  echo.
  pause
)

endlocal
