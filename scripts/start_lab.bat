@echo off
REM Start the centrality lab on Windows. Uses the .venv in the project folder if it exists.
cd /d "%~dp0.."
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
python -m streamlit run app.py %*
pause
