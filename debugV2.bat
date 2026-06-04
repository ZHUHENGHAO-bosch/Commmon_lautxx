@echo off
setlocal

:: 1. 指定 Python 解释器
set PYTHON_EXE=C:\toolbase\python\3.9.17.0.0\python-3.9.5.amd64\python.exe

:: 2. 动态获取当前 bat 所在的目录，并指向内部的 Python 脚本
set BASE_DIR=%~dp0
set PY_SCRIPT=%BASE_DIR%Scripts-common\api_debug.py

:: 3. 启动 Python，并将外部输入的所有参数 (%*) 原封不动地传递过去
"%PYTHON_EXE%" "%PY_SCRIPT%" %*