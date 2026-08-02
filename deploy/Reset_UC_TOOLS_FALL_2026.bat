@echo off
REM ============================================================
REM  UC GAA Maya 2026 - Full Reset (archive + reinstall)
REM  Run as Administrator, from the same folder as
REM  Install_UC_TOOLS_FALL_2026.bat (it calls that script by a
REM  path relative to itself, so both must stay together).
REM
REM  Archives C:\Cincy and this Windows account's Maya 2026 prefs
REM  to *_OLD folders (overwriting any previous archive from an
REM  earlier run of this script — only the most recent archive is
REM  kept, matching how the rest of today's cleanup has worked),
REM  then runs the full installer fresh against a clean slate.
REM
REM  Rigs are restored automatically — the main installer now syncs
REM  them from the server (step 10). Still NOT handled by anything
REM  in this pipeline: Configs\assignments_config.json (must be
REM  copied from the server manually, same as always) and ffmpeg
REM  (required by GAAPlayblastTool_V7.py). See the reminder printed
REM  at the end.
REM ============================================================

echo.
echo ============================================================
echo  UC GAA Maya 2026 - Full Reset
echo ============================================================
echo.

echo [1/3] Archiving C:\Cincy...
if exist "C:\Cincy_OLD" rd /S /Q "C:\Cincy_OLD"
if exist "C:\Cincy" (
    move "C:\Cincy" "C:\Cincy_OLD" >nul
    echo         Archived to C:\Cincy_OLD
) else (
    echo         C:\Cincy did not exist, nothing to archive.
)

echo [2/3] Archiving Maya 2026 prefs...
if exist "%USERPROFILE%\Documents\maya\2026_OLD" rd /S /Q "%USERPROFILE%\Documents\maya\2026_OLD"
if exist "%USERPROFILE%\Documents\maya\2026" (
    move "%USERPROFILE%\Documents\maya\2026" "%USERPROFILE%\Documents\maya\2026_OLD" >nul
    echo         Archived to %USERPROFILE%\Documents\maya\2026_OLD
) else (
    echo         Maya 2026 prefs did not exist, nothing to archive.
)

echo [3/3] Running full install...
call "%~dp0Install_UC_TOOLS_FALL_2026.bat"

echo.
echo ============================================================
echo  Reset complete. These still need manual attention:
echo    - Configs\assignments_config.json: copy from the server
echo    - ffmpeg: required by the Playblast tool, not handled here
echo ============================================================
echo.
pause
