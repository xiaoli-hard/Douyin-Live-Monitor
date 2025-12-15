@echo off
cd /d d:\Text\total\conclusion\conclusion
call .venv\Scripts\Activate.bat
python -c "import funasr; print('funasr imported successfully')"
.venv\Scripts\python.exe src\host_script_acquisition\SenseVoice_Pro.py
pause