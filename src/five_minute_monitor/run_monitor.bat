@echo off
echo Starting the 5-minute monitoring system...
cd /d "%~dp0"
python start_five_minute_monitor.py
pause