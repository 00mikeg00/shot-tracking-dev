@echo off
setlocal EnableDelayedExpansion
REM ============================================================
REM  UC GAA Maya 2026 - Fall Semester Lab Installer
REM  Run as daapo with admin elevation
REM
REM  Everything under \\artscifs1.ad.uc.edu\Departments\GAA\UC_GAA
REM  (except deploy\, professor-tools\, bat files\, and _OLD\) is
REM  meant to mirror exactly onto C:\Cincy on every lab machine --
REM  same server, same result, every machine. Folders are mirrored
REM  with robocopy /MIR, so a machine's local copy exactly matches
REM  the server: nothing added there survives, nothing missing here
REM  stays missing there.
REM
REM  Every copy (single file or /MIR) retries 3x on transient
REM  failures and logs to C:\Cincy\logs\install\install_log.txt --
REM  if a copy fails outright it's flagged at the end instead of
REM  silently leaving a partial file or folder behind.
REM
REM  assignments_config.json is written by Flask on save to both
REM  C:\Cincy\Configs on GAAAP1PRD01W (authoritative) and to
REM  %SRC%\Configs (mirror, for lab machines to pull from here).
REM  See save_assignment_config_semester() in the config routes.
REM ============================================================

set "HAD_ERRORS=0"
set "SRC=\\artscifs1.ad.uc.edu\Departments\GAA\UC_GAA"
set "LOG_DIR=C:\Cincy\logs\install"
set "INSTALL_LOG=%LOG_DIR%\install_log.txt"

echo.
echo ============================================================
echo  UC GAA Maya 2026 Lab Setup
echo ============================================================
echo.

REM -- 1. Create local folder structure -------------------------
echo [1/19] Creating local folder structure...
mkdir "C:\Cincy\MayaApp\2026\prefs" 2>nul
mkdir "C:\Cincy\MayaApp\2026\scripts" 2>nul
mkdir "C:\Cincy\MayaApp\2026\plug-ins" 2>nul
mkdir "C:\Cincy\Shelves" 2>nul
mkdir "C:\Cincy\scripts" 2>nul
mkdir "C:\Cincy\icons" 2>nul
mkdir "C:\Cincy\Rigs" 2>nul
mkdir "C:\Cincy\plug-ins" 2>nul
mkdir "C:\Cincy\Audio" 2>nul
mkdir "C:\Cincy\Pose Library" 2>nul
mkdir "C:\Cincy\ToonBoom" 2>nul
mkdir "C:\Cincy\modules" 2>nul
mkdir "C:\Cincy\ffmpeg" 2>nul
mkdir "C:\Cincy\python_libs" 2>nul
mkdir "C:\Cincy\Autosave" 2>nul
mkdir "%LOG_DIR%" 2>nul
mkdir "%USERPROFILE%\Documents\maya\2026\prefs" 2>nul
mkdir "%USERPROFILE%\Documents\maya\2026\scripts" 2>nul
del /F /Q "%INSTALL_LOG%" 2>nul

REM -- 1b. Cleanup legacy folders ---------------------------
echo [1b/19] Cleaning up legacy folders...
rd /S /Q "C:\Cincy\obs-bridge" 2>nul
rd /S /Q "C:\Cincy\review_manager" 2>nul
rd /S /Q "C:\Cincy\maya_tools" 2>nul
del /F /Q "C:\Cincy\Blinker.mb" 2>nul
del /F /Q "C:\Cincy\cleanup_done.flag" 2>nul
del /F /Q "C:\Cincy\ProRigs_Install_Bundle.zip" 2>nul
del /F /Q "%USERPROFILE%\Documents\maya\scripts\userSetup.py" 2>nul

REM -- 2. Deploy Maya.env to Documents --------------------------
echo [2/19] Deploying Maya.env...
robocopy "%SRC%\deploy\maya\2026" "%USERPROFILE%\Documents\maya\2026" Maya.env /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "Maya.env"

REM -- 3. Deploy userSetup.mel -----------------------------------
echo [3/19] Deploying userSetup.mel...
robocopy "%SRC%\deploy\maya\2026\scripts" "%USERPROFILE%\Documents\maya\2026\scripts" userSetup.mel /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "userSetup.mel (Documents)"
robocopy "%SRC%\deploy\maya\2026\scripts" "C:\Cincy\MayaApp\2026\scripts" userSetup.mel /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "userSetup.mel (Cincy)"

REM -- 4. Deploy userPrefs.mel -----------------------------------
echo [4/19] Deploying userPrefs.mel...
robocopy "%SRC%\deploy\maya\2026\prefs" "%USERPROFILE%\Documents\maya\2026\prefs" userPrefs.mel /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "userPrefs.mel (Documents)"
robocopy "%SRC%\deploy\maya\2026\prefs" "C:\Cincy\MayaApp\2026\prefs" userPrefs.mel /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "userPrefs.mel (Cincy)"

REM -- 5. Deploy pluginPrefs.mel (delete dirty, copy clean, lock)
echo [5/19] Deploying pluginPrefs.mel...
attrib -R "%USERPROFILE%\Documents\maya\2026\prefs\pluginPrefs.mel" 2>nul
del /F /Q "%USERPROFILE%\Documents\maya\2026\prefs\pluginPrefs.mel" 2>nul
robocopy "%SRC%\deploy\maya\2026\prefs" "%USERPROFILE%\Documents\maya\2026\prefs" pluginPrefs.mel /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "pluginPrefs.mel (Documents)"
attrib +R "%USERPROFILE%\Documents\maya\2026\prefs\pluginPrefs.mel"
robocopy "%SRC%\deploy\maya\2026\prefs" "C:\Cincy\MayaApp\2026\prefs" pluginPrefs.mel /IS /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "pluginPrefs.mel (Cincy)"

REM -- 6. Deploy CODE.mod ---------------------------------------
echo [6/19] Deploying CODE.mod...
robocopy "%SRC%\modules" "C:\Cincy" CODE.mod /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "CODE.mod"

REM -- 7. Deploy Maya scripts ------------------------------------
REM     Mirrors the whole scripts folder so anything placed there --
REM     FaceCam, UCSetSceneV1, studiolibrary, tweenMachinePython3,
REM     zvparentmaster, MG-PickerStudio, etc. -- deploys automatically.
echo [7/19] Deploying scripts...
robocopy "%SRC%\scripts" "C:\Cincy\scripts" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "scripts"

REM -- 8. Deploy GAA shelf ----------------------------------------
REM     Mirrors the top-level Shelves folder directly -- that IS the
REM     source of truth, not the copy under deploy\. A true mirror
REM     means only what's actually on the server survives locally,
REM     so this machine only ever has whatever shelf tabs the server
REM     folder has (currently just shelf_GAA.mel).
echo [8/19] Deploying GAA shelf...
robocopy "%SRC%\Shelves" "C:\Cincy\Shelves" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "Shelves"

REM -- 9. Deploy icons --------------------------------------------
echo [9/19] Deploying icons...
robocopy "%SRC%\icons" "C:\Cincy\icons" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "icons"

REM -- 10. Deploy Rigs --------------------------------------------
echo [10/19] Deploying rigs...
robocopy "%SRC%\Rigs" "C:\Cincy\Rigs" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "Rigs"

REM -- 11. Deploy plug-ins ----------------------------------------
echo [11/19] Deploying plug-ins...
robocopy "%SRC%\plug-ins" "C:\Cincy\plug-ins" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "plug-ins"

REM -- 12. Deploy Audio -------------------------------------------
echo [12/19] Deploying audio...
robocopy "%SRC%\Audio" "C:\Cincy\Audio" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "Audio"

REM -- 13. Deploy Pose Library ------------------------------------
echo [13/19] Deploying pose library...
robocopy "%SRC%\Pose Library" "C:\Cincy\Pose Library" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "Pose Library"

REM -- 14. Deploy ToonBoom ----------------------------------------
echo [14/19] Deploying ToonBoom...
robocopy "%SRC%\ToonBoom" "C:\Cincy\ToonBoom" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "ToonBoom"

REM -- 15. Deploy modules -----------------------------------------
REM     CODE.mod itself is already handled explicitly in step 6
REM     (that's the proven, working path) -- this additionally mirrors
REM     the whole modules folder in case anything else lives there.
echo [15/19] Deploying modules...
robocopy "%SRC%\modules" "C:\Cincy\modules" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "modules"

REM -- 16. Deploy python_libs -------------------------------------
REM     requests + its dependencies (certifi, charset_normalizer,
REM     idna, urllib3) for Maya's embedded Python, which has no pip
REM     packages of its own. Content sync only -- import requests has
REM     already been working throughout everything tested today, so
REM     something else already puts this folder on Python's path
REM     (system-wide PYTHONPATH, set outside anything in this repo).
REM     Not touching that mechanism since it's already working.
echo [16/19] Deploying python_libs...
robocopy "%SRC%\python_libs" "C:\Cincy\python_libs" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "python_libs"

REM -- 17. Deploy ffmpeg ------------------------------------------
REM     Mirrors the folder, then adds C:\Cincy\ffmpeg\bin to the
REM     machine PATH so shutil.which("ffmpeg") in
REM     GAAPlayblastTool_V7.py can find it. Uses PowerShell's
REM     [Environment]::SetEnvironmentVariable instead of setx, which
REM     silently truncates PATH past 1024 characters -- a real risk
REM     on a machine with this much software already on PATH. Checks
REM     for an existing entry first so repeat runs don't pile up
REM     duplicates.
echo [17/19] Deploying ffmpeg...
robocopy "%SRC%\ffmpeg" "C:\Cincy\ffmpeg" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "ffmpeg"
powershell -NoProfile -Command "$p = [Environment]::GetEnvironmentVariable('Path','Machine'); if ($p -notlike '*C:\Cincy\ffmpeg\bin*') { [Environment]::SetEnvironmentVariable('Path', $p + ';C:\Cincy\ffmpeg\bin', 'Machine') }"

REM -- 18. Deploy assignments_config.json from the Flask server --
REM     NOT from %SRC% -- the copy under the share is stale/orphaned
REM     (see note at top of this file). The real, current file only
REM     ever exists at C:\Cincy\Configs\assignments_config.json on
REM     GAAAP1PRD01W itself, regenerated by Flask on every admin save.
REM     Pulled via that machine's c$ admin share, which requires the
REM     account running this installer to have admin rights there.
REM     Always overwritten (no /XO or timestamp check) -- unlike every
REM     other step, this one must reflect the server's current state
REM     every run, not just sync deltas.
echo [18/20] Deploying assignments_config.json...
robocopy "\\GAAAP1PRD01W\c$\Cincy\Configs" "C:\Cincy\Configs" assignments_config.json /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "assignments_config.json"

REM -- 19. Deploy capstone_config_v1.json from the Flask server --
REM     Same reasoning and same c$ admin-share pull as assignments_config.json
REM     above -- the real, current file only ever exists at
REM     C:\Cincy\Configs\capstone_config_v1.json on GAAAP1PRD01W, regenerated
REM     by Flask's /films/config/api/save-json on every admin save. Always
REM     overwritten, not synced from %SRC%.
echo [19/20] Deploying assignments_config.json...
robocopy "%SRC%\Configs" "C:\Cincy\Configs" assignments_config.json /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "assignments_config.json"

REM -- 20. Add shottracker:// URI scheme to registry ------------
echo [20/20] Registering shottracker:// URI scheme...
reg add "HKLM\SOFTWARE\Classes\shottracker" /ve /d "URL:Shot Tracker Protocol" /f
reg add "HKLM\SOFTWARE\Classes\shottracker" /v "URL Protocol" /d "" /f
reg add "HKLM\SOFTWARE\Classes\shottracker\shell\open\command" /ve /d "\"C:\Program Files\Autodesk\Maya2026\bin\mayapy.exe\" \"C:\Cincy\scripts\launcher.py\" \"%%1\"" /f

echo.
echo ============================================================
if "%HAD_ERRORS%"=="1" (
    echo  DONE WITH ERRORS - one or more steps failed to copy fully.
    echo  Check the log below, then re-run this installer to retry
    echo  just the missing pieces ^(robocopy only copies what's
    echo  actually missing or different^):
    echo    %INSTALL_LOG%
) else (
    echo  Done. Maya 2026 environment configured.
)
echo ============================================================
echo.
pause
goto :EOF

:CheckRC
REM  Robocopy exit codes 0-7 are success/informational (files copied,
REM  extra files, mismatches noted). 8+ means real failures occurred --
REM  something didn't make it across even after 3 retries.
REM
REM  %~1/%~2 are copied into named variables and referenced with !...!
REM  (delayed expansion, already enabled via setlocal above) INSIDE the
REM  if (...) block rather than %~1/%~2 directly -- labels like
REM  "userSetup.mel (Documents)" contain literal parentheses, and
REM  non-delayed %-expansion happens as part of the parser's initial
REM  scan for the block's own matching close-paren, before the block
REM  ever executes. That makes the label's "(Documents)" get mistaken
REM  for the block's real closing paren, breaking with "X was unexpected
REM  at this time" -- confirmed by reproducing it standalone. Delayed
REM  expansion defers substitution until each line inside the
REM  already-correctly-parsed block actually runs, so it can't confuse
REM  the parser this way.
set "RC_VAL=%~1"
set "RC_LABEL=%~2"
if !RC_VAL! GEQ 8 (
    echo    *** ERROR: !RC_LABEL! failed to copy - robocopy exit code !RC_VAL! - see %INSTALL_LOG% ***
    set "HAD_ERRORS=1"
)
exit /b
