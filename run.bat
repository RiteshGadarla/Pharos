@echo off
rem ============================================================================
rem  DRISHTA (Slicktrace) - run the app on Windows.
rem  Starts the core service (:8000) and the operator console (:5173) together.
rem  Ctrl+C stops both. Forwards arguments, e.g.  run.bat -Offline
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "PS=powershell"
where pwsh >nul 2>&1 && set "PS=pwsh"

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
set "RC=%ERRORLEVEL%"

rem Keep the window open only on a genuine double-click (Explorer launches us
rem as `cmd /c "<path>\run.bat"`, so our own path appears in %cmdcmdline%).
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
