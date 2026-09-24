@echo off
rem ============================================================================
rem  DRISHTA (Slicktrace) - Windows setup launcher.
rem  Double-click this file, or run it from a terminal. It just runs setup.ps1
rem  with the execution policy relaxed so nobody has to fight PowerShell first.
rem  Any arguments are forwarded, e.g.  setup.bat -QuickSeed
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "PS=powershell"
where pwsh >nul 2>&1 && set "PS=pwsh"

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set "RC=%ERRORLEVEL%"

rem Keep the window open only on a genuine double-click (Explorer launches us
rem as `cmd /c "<path>\setup.bat"`, so our own path appears in %cmdcmdline%).
rem Never pause under automation: define DRISHTA_NO_PAUSE, or pass any argument.
rem The substring test avoids `echo %cmdcmdline%`, which a metacharacter in the
rem install path (& | < > ^ parentheses) would otherwise mis-parse.
if defined DRISHTA_NO_PAUSE goto :nopause
if not "%~1"=="" goto :nopause
setlocal EnableDelayedExpansion
if not "!cmdcmdline:%~f0=!"=="!cmdcmdline!" pause
endlocal
:nopause

exit /b %RC%
