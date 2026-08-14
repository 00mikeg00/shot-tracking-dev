@echo off
REM launcher_wrapper.bat
REM UC GAA Shot Tracker -- shottracker:// registry target
REM
REM Registered directly as a raw .exe (mayapy.exe), the shottracker:// handler
REM was silently dying on at least one lab machine -- the console flashed and
REM closed with no log output at all, before launcher.py's own logging could
REM even start. Confirmed via manual mayapy.exe invocation from cmd, which
REM worked every time with the identical command line. Going through cmd.exe
REM as an intermediary (this wrapper) instead of invoking mayapy.exe directly
REM as the registered handler fixed it -- root cause not confirmed (suspected
REM endpoint security treating a raw .exe launched by a browser protocol
REM handler with more scrutiny than one launched by cmd.exe), but this is a
REM safe, reversible fix either way.
"C:\Program Files\Autodesk\Maya2026\bin\mayapy.exe" "C:\Cincy\scripts\launcher.py" "%~1" >> C:\Cincy\logs\launcher_log.txt 2>&1
echo [%date% %time%] Exit code: %ERRORLEVEL% >> C:\Cincy\logs\launcher_log.txt
