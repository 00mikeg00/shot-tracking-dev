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
REM
REM  capstone_config_v1.json is STILL pulled via the GAAAP1PRD01W
REM  c$ admin share (step 19) -- this is a KNOWN BUG, same root
REM  cause as the old assignments_config.json failure. SYSTEM on a
REM  lab machine has no rights on GAAAP1PRD01W's c$ share, so this
REM  step will keep failing until Flask is updated to also mirror
REM  capstone_config_v1.json to %SRC%\Configs on save, the same way
REM  assignments_config.json already was fixed. Flagged for a
REM  follow-up fix, not blocking this deploy.
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
echo [1/21] Creating local folder structure...
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
del /F /Q "%INSTALL_LOG%" 2>nul
REM NOTE: %USERPROFILE%\Documents\maya\2026\{prefs,scripts} mkdirs
REM removed -- confirmed dead weight. MAYA_APP_DIR=C:\Cincy\MayaApp
REM means Maya reads C:\Cincy\MayaApp\2026\{prefs,scripts} instead,
REM and under SYSTEM this script's %USERPROFILE% resolves to the
REM SYSTEM profile anyway, not any student's.

REM -- 1b. Cleanup legacy folders ---------------------------
echo [1b/21] Cleaning up legacy folders...
rd /S /Q "C:\Cincy\obs-bridge" 2>nul
rd /S /Q "C:\Cincy\review_manager" 2>nul
rd /S /Q "C:\Cincy\maya_tools" 2>nul
del /F /Q "C:\Cincy\Blinker.mb" 2>nul
del /F /Q "C:\Cincy\cleanup_done.flag" 2>nul
del /F /Q "C:\Cincy\ProRigs_Install_Bundle.zip" 2>nul
del /F /Q "%USERPROFILE%\Documents\maya\scripts\userSetup.py" 2>nul
del /F /Q "C:\Cincy\plug-ins\PRLicensePlugin.mll" 2>nul
REM Stale Maya.env at the OLD default location (Documents\maya\2026),
REM left over from before MAYA_APP_DIR was set at the OS level (see
REM step 2). Once MAYA_APP_DIR redirects Maya to C:\Cincy\MayaApp,
REM Maya stops reading this file -- but on machines imaged/updated
REM before this fix, it's still sitting there. Harmless once
REM MAYA_APP_DIR takes effect, but removed anyway so there's no
REM confusion later about which Maya.env is "the real one," and no
REM risk from it if MAYA_APP_DIR ever fails to apply on some machine.
del /F /Q "%USERPROFILE%\Documents\maya\2026\Maya.env" 2>nul

REM -- 2. Set MAYA_APP_DIR at the OS/machine level ---------------
REM     MUST be a real machine environment variable, not just a line
REM     inside Maya.env -- Maya resolves MAYA_APP_DIR (to find
REM     Maya.env in the first place) BEFORE it ever parses Maya.env,
REM     using its own default (%USERPROFILE%\Documents\maya) unless
REM     an OS-level env var says otherwise. A MAYA_APP_DIR= line
REM     inside Maya.env is read too late to have any effect.
REM     Uses [Environment]::SetEnvironmentVariable, not setx, for the
REM     same reason as the ffmpeg PATH step below (setx silently
REM     truncates past 1024 chars). Checks current value first so
REM     repeat runs don't do pointless rewrites.
echo [2/21] Setting MAYA_APP_DIR (machine environment variable)...
powershell -NoProfile -Command "$cur = [Environment]::GetEnvironmentVariable('MAYA_APP_DIR','Machine'); if ($cur -ne 'C:\Cincy\MayaApp') { [Environment]::SetEnvironmentVariable('MAYA_APP_DIR', 'C:\Cincy\MayaApp', 'Machine') }"

REM -- 2b. Set PYTHONPATH at the OS/machine level ------------------
REM     mayapy.exe's embedded Python has no pip packages of its own
REM     and does not pick up C:\Cincy\python_libs automatically --
REM     launcher.py fails immediately with
REM     "ModuleNotFoundError: No module named 'requests'" without
REM     this. Confirmed missing on a fresh machine 2026-08-10.
echo [2b/21] Setting PYTHONPATH (machine environment variable)...
powershell -NoProfile -Command "$cur = [Environment]::GetEnvironmentVariable('PYTHONPATH','Machine'); if ($cur -notlike '*C:\Cincy\python_libs*') { [Environment]::SetEnvironmentVariable('PYTHONPATH', 'C:\Cincy\python_libs', 'Machine') }"

REM -- 3. Deploy Maya.env ------------------------------------------
REM     Now targets C:\Cincy\MayaApp\2026 -- with MAYA_APP_DIR set at
REM     the OS level (step 2), that's where Maya will actually look
REM     for Maya.env, not Documents\maya\2026 anymore.
echo [3/21] Deploying Maya.env...
robocopy "%SRC%\deploy\maya\2026" "C:\Cincy\MayaApp\2026" Maya.env /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "Maya.env"

REM -- 4. Deploy userSetup.mel -----------------------------------
echo [4/21] Deploying userSetup.mel...
REM Documents-targeted copy removed: under SYSTEM, %USERPROFILE%
REM resolves to the SYSTEM profile, not the student's, and
REM MAYA_APP_DIR=C:\Cincy\MayaApp means Maya never reads from
REM Documents anyway. This copy is the one that matters.
robocopy "%SRC%\deploy\maya\2026\scripts" "C:\Cincy\MayaApp\2026\scripts" userSetup.mel /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "userSetup.mel (Cincy)"

REM -- 5. Deploy userPrefs.mel -----------------------------------
echo [5/21] Deploying userPrefs.mel...
REM Documents-targeted copy removed -- same reasoning as step 3.
robocopy "%SRC%\deploy\maya\2026\prefs" "C:\Cincy\MayaApp\2026\prefs" userPrefs.mel /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "userPrefs.mel (Cincy)"

REM -- 6. Deploy pluginPrefs.mel (delete dirty, copy clean, lock)
echo [6/21] Deploying pluginPrefs.mel...
REM Documents-targeted delete/copy/lock removed -- was silently
REM locking a file under the SYSTEM profile that Maya never reads
REM (MAYA_APP_DIR redirects to C:\Cincy\MayaApp), while leaving the
REM file Maya actually uses unlocked. Lock now applied to the
REM correct, actually-read file below.
attrib -R "C:\Cincy\MayaApp\2026\prefs\pluginPrefs.mel" 2>nul
del /F /Q "C:\Cincy\MayaApp\2026\prefs\pluginPrefs.mel" 2>nul
robocopy "%SRC%\deploy\maya\2026\prefs" "C:\Cincy\MayaApp\2026\prefs" pluginPrefs.mel /IS /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "pluginPrefs.mel (Cincy)"
attrib +R "C:\Cincy\MayaApp\2026\prefs\pluginPrefs.mel"

REM -- 7. Deploy CODE.mod ---------------------------------------
echo [7/21] Deploying CODE.mod...
robocopy "%SRC%\modules" "C:\Cincy" CODE.mod /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "CODE.mod"

REM -- 8. Deploy Maya scripts ------------------------------------
REM     Mirrors the whole scripts folder so anything placed there --
REM     FaceCam, UCSetSceneV1, studiolibrary, tweenMachinePython3,
REM     zvparentmaster, MG-PickerStudio, etc. -- deploys automatically.
echo [8/21] Deploying scripts...
robocopy "%SRC%\scripts" "C:\Cincy\scripts" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "scripts"

REM -- 9. Deploy GAA shelf ----------------------------------------
REM     Mirrors the top-level Shelves folder directly -- that IS the
REM     source of truth, not the copy under deploy\. A true mirror
REM     means only what's actually on the server survives locally,
REM     so this machine only ever has whatever shelf tabs the server
REM     folder has (currently just shelf_GAA.mel).
echo [9/21] Deploying GAA shelf...
robocopy "%SRC%\Shelves" "C:\Cincy\Shelves" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "Shelves"

REM -- 9b. Deploy GAA shelf cache -----------------------------------
REM     Root-caused 2026-08-05: Maya's shelf UI loads shelf tabs from
REM     C:\Cincy\MayaApp\2026\prefs\shelves\ at startup, NOT by
REM     re-sourcing MAYA_SHELF_PATH fresh each launch like every
REM     other MAYA_*_PATH variable. Built-in shelves (Arnold,
REM     Bifrost, MASH, etc.) already have this cache file baked in
REM     from the Maya install itself; shelf_GAA.mel never did, since
REM     it's custom. Without this step, the GAA tab is correctly
REM     registered (via userPrefs.mel's shelfName17/shelfFile17) but
REM     loads empty on every single launch, regardless of how
REM     correct/current C:\Cincy\Shelves\shelf_GAA.mel itself is.
REM     Per-profile, not machine-wide -- must run for every student
REM     the same as steps 4/5/6.
echo [9b/21] Deploying GAA shelf cache...
robocopy "C:\Cincy\Shelves" "C:\Cincy\MayaApp\2026\prefs\shelves" shelf_GAA.mel /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "GAA shelf cache"

REM -- 10. Deploy icons --------------------------------------------
echo [10/21] Deploying icons...
robocopy "%SRC%\icons" "C:\Cincy\icons" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "icons"

REM -- 11. Deploy Rigs --------------------------------------------
echo [11/21] Deploying rigs...
robocopy "%SRC%\Rigs" "C:\Cincy\Rigs" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "Rigs"

REM -- 12. Deploy plug-ins ----------------------------------------
echo [12/21] Deploying plug-ins...
robocopy "%SRC%\plug-ins" "C:\Cincy\plug-ins" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "plug-ins"

REM -- 13. Deploy Audio -------------------------------------------
echo [13/21] Deploying audio...
robocopy "%SRC%\Audio" "C:\Cincy\Audio" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "Audio"

REM -- 14. Deploy Pose Library ------------------------------------
echo [14/21] Deploying pose library...
robocopy "%SRC%\Pose Library" "C:\Cincy\Pose Library" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "Pose Library"

REM -- 15. Deploy ToonBoom ----------------------------------------
echo [15/21] Deploying ToonBoom...
robocopy "%SRC%\ToonBoom" "C:\Cincy\ToonBoom" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "ToonBoom"

REM -- 16. Deploy modules -----------------------------------------
REM     CODE.mod itself is already handled explicitly in step 6
REM     (that's the proven, working path) -- this additionally mirrors
REM     the whole modules folder in case anything else lives there.
echo [16/21] Deploying modules...
robocopy "%SRC%\modules" "C:\Cincy\modules" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "modules"

REM -- 17. Deploy python_libs -------------------------------------
REM     requests + its dependencies (certifi, charset_normalizer,
REM     idna, urllib3) for Maya's embedded Python, which has no pip
REM     packages of its own. Content sync only -- import requests has
REM     already been working throughout everything tested today, so
REM     something else already puts this folder on Python's path
REM     (system-wide PYTHONPATH, set outside anything in this repo).
REM     Not touching that mechanism since it's already working.
echo [17/21] Deploying python_libs...
robocopy "%SRC%\python_libs" "C:\Cincy\python_libs" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "python_libs"

REM -- 18. Deploy ffmpeg ------------------------------------------
REM     Mirrors the folder, then adds C:\Cincy\ffmpeg\bin to the
REM     machine PATH so shutil.which("ffmpeg") in
REM     GAAPlayblastTool_V7.py can find it. Uses PowerShell's
REM     [Environment]::SetEnvironmentVariable instead of setx, which
REM     silently truncates PATH past 1024 characters -- a real risk
REM     on a machine with this much software already on PATH. Checks
REM     for an existing entry first so repeat runs don't pile up
REM     duplicates.
echo [18/21] Deploying ffmpeg...
robocopy "%SRC%\ffmpeg" "C:\Cincy\ffmpeg" /MIR /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "ffmpeg"
powershell -NoProfile -Command "$p = [Environment]::GetEnvironmentVariable('Path','Machine'); if ($p -notlike '*C:\Cincy\ffmpeg\bin*') { [Environment]::SetEnvironmentVariable('Path', $p + ';C:\Cincy\ffmpeg\bin', 'Machine') }"

REM -- 19. Deploy assignments_config.json from the Flask server --
REM     Pulled from %SRC%\Configs, not the GAAAP1PRD01W c$ admin
REM     share -- Flask now mirrors this file to %SRC%\Configs on
REM     every save (see save_assignment_config_semester()), so this
REM     matches every other step's mirror-based pull. The old c$
REM     pull failed here because SYSTEM on a lab machine has no
REM     rights on GAAAP1PRD01W's admin share (confirmed via
REM     install_log ERROR 5, 2026-08-10).
echo [19/21] Deploying assignments_config.json...
robocopy "%SRC%\Configs" "C:\Cincy\Configs" assignments_config.json /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "assignments_config.json"

REM -- 20. Add shottracker:// URI scheme to registry ------------
echo [20/21] Registering shottracker:// URI scheme...
reg add "HKLM\SOFTWARE\Classes\shottracker" /ve /d "URL:Shot Tracker Protocol" /f
reg add "HKLM\SOFTWARE\Classes\shottracker" /v "URL Protocol" /d "" /f
reg add "HKLM\SOFTWARE\Classes\shottracker\shell\open\command" /ve /d "\"C:\Program Files\Autodesk\Maya2026\bin\mayapy.exe\" \"C:\Cincy\scripts\launcher.py\" \"%%1\"" /f

REM -- 21. Deploy Shot Tracker desktop shortcut --------------------
REM     Public\Desktop (not per-user) so it shows up for every student
REM     on a shared lab machine without needing per-profile deployment.
REM     Source and dest keep the identical "Shot Tracker.url" filename
REM     since robocopy copies a file's name as-is, it can't rename on
REM     the way through.
echo [21/21] Deploying Shot Tracker desktop shortcut...
robocopy "%SRC%\deploy\shortcuts" "C:\Users\Public\Desktop" "Shot Tracker.url" /R:3 /W:5 /LOG+:"%INSTALL_LOG%"
set RC=%ERRORLEVEL%
call :CheckRC %RC% "Shot Tracker.url"

echo.
echo ============================================================
if "%HAD_ERRORS%"=="1" (
    echo  DONE WITH ERRORS - one or more steps failed to copy fully.
    echo  Check the log below, then re-run this installer to retry
    echo  just the missing pieces ^(robocopy only copies what's
    echo  actually missing or different^):
    echo    %INSTALL_LOG%
) else (
    echo  Done! Maya 2026 environment configured.
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
