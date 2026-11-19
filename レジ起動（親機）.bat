@echo off
rem Start the register as the main PC (child terminals on the same Wi-Fi can connect).
rem Close this window to stop the register.
cd /d "%~dp0"
python web_main.py --lan
pause
