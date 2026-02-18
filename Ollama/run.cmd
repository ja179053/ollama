@ECHO OFF
REM This script acts as a shortcut to launch the Python script
REM and keep the console window open afterward.
REM ***************************************************************
REM *** CONFIGURE THE PATHS BELOW ***
REM
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
REM 1. PYTHON_EXE: The full path to your Python interpreter.
@echo off
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo Starting Monitoring Engine from %SCRIPT_DIR%...
dotnet run --project ./MonitoringEngine
pause

SET VENV="%SCRIPT_DIR%pythonenv\Scripts"
ECHO %VENV%   
REM 2. SCRIPT_PATH: The full path to the file you want to run (e.g., your run.py)
SET SCRIPT_PATH="%SCRIPT_DIR%run.py"
REM ***************************************************************
CALL "%VENV%\activate"
ECHO Running specified file: %SCRIPT_PATH%
ECHO ----------------------------------------------------
REM *** UNCONDITIONAL LAUNCH ***
REM The actual single-instance check is now handled INSIDE the Python script (via socket binding).
REM If an instance is already running, the Python script will print an error and exit immediately.
::  %PYTHON_EXE% %SCRIPT_PATH%
"%VENV%\python.exe" %SCRIPT_PATH%

REM --- End Script Section ---
ECHO.
ECHO --- Console remains open. Press any key to close. ---
PAUSE
cmd /k