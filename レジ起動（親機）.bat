@echo off
chcp 65001 >nul
rem レジを親機として起動する（同じ Wi-Fi・Tailscale の子機からつなげる）。
rem レジが止まったら、5 秒後に自動で起動し直す。
rem 止めるときは、このウィンドウを閉じる。
cd /d "%~dp0"
set RESTART_ARG=
:loop
python web_main.py --lan %RESTART_ARG%
rem 3 = すでにレジが起動している・ポートが使えないので起動しなかった（起動し直さない）
if "%errorlevel%"=="3" goto end
echo.
echo ================================================================
echo   レジが止まりました（%date% %time%）。
echo   5 秒後に自動で起動し直します。止めたいときはこのウィンドウを閉じてください。
echo ================================================================
timeout /t 5 /nobreak >nul
set RESTART_ARG=--restarted
goto loop
:end
pause
