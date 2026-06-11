@echo off
setlocal

set PYTHON_EXE=C:\toolbase\python\3.9.17.0.0\python-3.9.5.amd64\python.exe

set BASE_DIR=%~dp0
set PY_SCRIPT=%BASE_DIR%Scripts-common\api_debug.py

"%PYTHON_EXE%" "%PY_SCRIPT%" %*
