"""
GAAPlayblastTool_V7.py
UC GAA Playblast / Submission Tool — Maya 2026

Renders locally to C:/Temp, converts to webm via ffmpeg, then copies the
result to the class's network Assignments folder and notifies Shot Tracker.

Rewritten from V6 to work with the current system:
  - Reads scene identity (class/assignment/individual_assignment_id/semester/
    display name) from cmds.fileInfo tags stamped by Assignments.py, instead
    of requiring them to already exist with no way to set them, or parsing
    them out of the filename.
  - Never opens the database directly. V6 connected to app.db over a UNC
    path to write assignment status itself, competing with Flask's own
    writes to the same file — the same kind of contention that produces
    "database is locked" errors. V7 always goes through Flask's
    /classes/api/launcher/submit-assignment endpoint instead (unauthenticated,
    same trust model as the launcher: security boundary is the intranet).
  - UNC host uses the FQDN (gaaap1prd01w.ad.uc.edu), matching the convention
    confirmed for the rest of the system.
  - Dropped the CAMP_MODE flag that unconditionally redirected every
    assignment submission to the DAAP CAMP folder regardless of actual
    class — almost certainly a debug leftover, not something to carry
    forward silently.

Film-shot submission is largely unchanged from V6: it already went through
Flask's /review endpoints (unauthenticated, no direct DB access), so it
didn't have the same problem the assignment path did. Only the UNC host
and a couple of small cleanups changed there.
"""

import os
import re
import shutil
import subprocess
import time
import requests
import maya.cmds as cmds


SHOT_TRACKER_URL = "http://10.23.20.210:8000"
UNC_BASE = r"\\gaaap1prd01w.ad.uc.edu\Classes"

audio_checkbox = None
step_menu = None

STEP_CODES = {
    "Blocking": "BL",
    "Blocking Plus": "BP",
    "Polish": "P"
}
ASSIGNMENT_STEP_NAME_MAP = {
    "PL": "Planning",
    "BL": "Blocking",
    "BP": "Blocking Plus",
    "P": "Polish"
}
FILM_STEP_CODES = ["LAY", "ANIM", "LIT"]


# ─────────────────────────────────────────────
#  FILENAME / SCENE-TYPE HELPERS
# ─────────────────────────────────────────────

def is_film_scene(filename):
    """
    Detect FILM_SCENE_SHOT_STEP_USER_v# pattern.
    Example: Vacation_010_010_LAY_Mike_v1.mb
    """
    name = os.path.splitext(filename)[0]
    parts = name.rsplit("_", 5)
    if len(parts) != 6:
        return False

    film, scene, shot, step, user, version = parts
    if not re.match(r"^\d{3}$", scene):
        return False
    if not re.match(r"^\d{3}$", shot):
        return False
    if not version.lower().startswith("v"):
        return False
    return True


def get_scene_metadata():
    """
    Reads the GAA_* fileInfo tags Assignments.py stamps onto every scene it
    creates or opens. Fields are None if this scene wasn't created by it
    (e.g. an old scene predating this tagging, or a film scene — films are
    identified by filename instead, see is_film_scene).
    """
    def _fi(key):
        val = cmds.fileInfo(key, q=True)
        return val[0] if val else None

    return {
        "class_name": _fi("GAA_class"),
        "assignment_name": _fi("GAA_assignment"),
        "individual_assignment_id": _fi("GAA_individual_assignment_id"),
        "semester": _fi("GAA_semester"),
        "display_name": _fi("GAA_display_name"),
    }


def get_render_cam():
    for cam_shape in cmds.ls(type="camera"):
        if cmds.getAttr(f"{cam_shape}.renderable"):
            cam_transform = cmds.listRelatives(cam_shape, parent=True)[0]
            if cam_transform not in ("persp", "top", "front", "side"):
                return cam_transform
    return "persp"


def get_selected_step_code():
    """
    Priority:
      1) 'Override Step' checkbox enabled -> read from the UI dropdown.
      2) Else infer from filename suffix (_PL/_BL/_BP/_P). If absent -> ''.
    """
    try:
        if step_menu and cmds.checkBox("enableStepCheckbox", q=True, value=True):
            step_label = cmds.optionMenu(step_menu, q=True, value=True)
            return STEP_CODES.get(step_label, "")
    except Exception:
        pass

    try:
        current_path = cmds.file(q=True, sn=True) or ""
        name_no_ext = os.path.splitext(os.path.basename(current_path))[0]
        m = re.search(r"_(PL|BL|BP|P)_v\d+$", name_no_ext, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    except Exception:
        pass

    return ""


def toggle_step_menu(state):
    if step_menu and cmds.optionMenu(step_menu, q=True, exists=True):
        cmds.optionMenu(step_menu, edit=True, enable=state)


# ─────────────────────────────────────────────
#  FILE HELPERS
# ─────────────────────────────────────────────

def safe_delete_file(path, max_retries=5, delay=0.5):
    for i in range(max_retries):
        try:
            os.remove(path)
            print(f"[CLEANUP] Deleted: {path}")
            return True
        except Exception as e:
            print(f"[RETRY {i + 1}] Failed to delete {path}: {e}")
            time.sleep(delay)
    try:
        if os.name == "nt":
            subprocess.Popen(["cmd", "/c", "del", "/f", "/q", path], shell=True)
            print(f"[CLEANUP] Scheduled deferred deletion for: {path}")
        else:
            os.remove(path)
    except Exception as e:
        print(f"[FAIL] Could not delete or schedule deletion: {e}")
    return False


def get_class_output_folder(semester, class_name):
    """
    Builds (and creates if missing) the class's Assignments folder on the
    network share, from the scene's own GAA_semester/GAA_class tags —
    no config-file read, no database access needed for this.
    """
    if not semester or not class_name:
        print("[DEBUG] Missing semester or class_name for output folder resolution")
        return None

    try:
        base_semester = os.path.normpath(os.path.join(UNC_BASE, semester))
        class_folder = os.path.normpath(os.path.join(base_semester, class_name))
        resolved_path = os.path.normpath(os.path.join(class_folder, "Assignments"))

        for p in [base_semester, class_folder, resolved_path]:
            if os.path.exists(p):
                if not os.path.isdir(p):
                    raise RuntimeError(f"Expected a folder but found a FILE: {p}")
            else:
                os.makedirs(p, exist_ok=True)
                print(f"[DEBUG] Created folder: {p}")

        return resolved_path
    except Exception as e:
        print(f"[ERROR] Failed to resolve/create output folder: {e}")
        return None


def get_next_versioned_path(base_path):
    """
    Scans the folder for versions (with or without _R) and returns the next
    available version path.
      - _R counts as a valid version.
      - If the highest version exists only as _R, bump from it automatically.
      - If a plain (non-_R) version exists at the highest number, confirm
        with the user before deleting it and bumping.
    """
    directory, filename = os.path.split(base_path)
    name, ext = os.path.splitext(filename)

    base_prefix = re.sub(r"_v\d+(_R)?$", "", name, flags=re.IGNORECASE)

    existing_versions = {}
    for f in os.listdir(directory):
        if not f.lower().endswith(ext.lower()):
            continue
        f_name, _ = os.path.splitext(f)
        if not f_name.startswith(base_prefix):
            continue

        reviewed_match = re.match(rf"^{re.escape(base_prefix)}_v(\d+)_R$", f_name, re.IGNORECASE)
        plain_match = re.match(rf"^{re.escape(base_prefix)}_v(\d+)$", f_name, re.IGNORECASE)

        if plain_match:
            existing_versions[int(plain_match.group(1))] = "plain"
        elif reviewed_match:
            existing_versions.setdefault(int(reviewed_match.group(1)), "reviewed")

    if not existing_versions:
        return os.path.join(directory, f"{base_prefix}_v1{ext}")

    highest_version = max(existing_versions.keys())

    if existing_versions[highest_version] == "reviewed":
        return os.path.join(directory, f"{base_prefix}_v{highest_version + 1}{ext}")

    current_file = os.path.join(directory, f"{base_prefix}_v{highest_version}{ext}")
    if os.path.exists(current_file):
        result = cmds.confirmDialog(
            title="File Exists",
            message=(f"{os.path.basename(current_file)} already exists.\n\n"
                      f"Do you want to bump to v{highest_version + 1}?\n"
                      f"(If yes, v{highest_version} will be deleted)"),
            button=["Yes", "No"],
            defaultButton="Yes",
            cancelButton="No",
            dismissString="No"
        )
        if result != "Yes":
            print("[RESULT] User cancelled bump.")
            return None
        try:
            os.remove(current_file)
        except Exception as e:
            print(f"[WARNING] Could not delete {current_file}: {e}")

    return os.path.join(directory, f"{base_prefix}_v{highest_version + 1}{ext}")


def _build_burn_in_text(step_code, display_name, assignment_name):
    """
    step | display name | assignment name, e.g. "BP | Meredith Burgess |
    BallBounce" -- omits the step segment when there isn't one (no step
    resolved) rather than showing a blank leading " | ".
    """
    parts = [p for p in (step_code, display_name, assignment_name) if p]
    return " | ".join(parts)


def _drawtext_filter(textfile_path):
    """
    Top-right burn-in, same font/box styling already proven in
    perform_film_playblast's HUD. Reads the burn-in text from a small
    temp file (textfile=) instead of embedding it inline as text='...' --
    verified against a real ffmpeg build that inline embedding can't
    reliably represent a literal apostrophe: ffmpeg's filtergraph parser
    accepts the standard close-quote/escaped-quote/reopen-quote trick
    ('\'' for a literal ') without erroring, but silently drops the
    character rather than rendering it. textfile= sidesteps the
    filtergraph's own text-escaping entirely, since the content never
    appears in the filter string. expansion=none stops drawtext from
    treating a literal '%' in the text as the start of its own %{...}
    expansion syntax (display/assignment names are free text from the
    database and could plausibly contain any of these).

    Only the file *path* needs the drive-letter colon escaped, same
    convention already used for fontfile.
    """
    path_fwd = textfile_path.replace("\\", "/")
    escaped_path = path_fwd.replace(":", "\\:", 1)
    return (
        f"drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':"
        f"textfile='{escaped_path}':"
        f"expansion=none:"
        f"x=(w-text_w)-20:y=20:"
        f"fontsize=14:fontcolor=white:borderw=2:"
        f"box=1:boxcolor=black@0.25:boxborderw=12"
    )


def convert_to_webm(avi_path, webm_path, burn_in_text=None):
    if not shutil.which("ffmpeg"):
        cmds.confirmDialog(
            title="FFmpeg Not Found",
            message="To submit, FFmpeg must be installed.\nPlease contact your instructor.",
            button=["OK"]
        )
        return False

    # fps=24,setpts=... must stay first in the chain -- drawtext is
    # appended after it with a comma, not passed as a separate -vf (which
    # would silently drop the fps/setpts pass instead of chaining after it).
    vf_chain = "fps=24,setpts=N/24/TB"
    textfile_path = None
    if burn_in_text:
        textfile_path = os.path.splitext(avi_path)[0] + "_burnin.txt"
        with open(textfile_path, "w", encoding="utf-8") as f:
            f.write(burn_in_text)
        vf_chain += "," + _drawtext_filter(textfile_path)

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", avi_path,
                "-c:v", "libvpx-vp9",
                "-b:v", "2M",
                "-g", "1",
                "-auto-alt-ref", "0",
                "-cpu-used", "4",
                "-vf", vf_chain,
                "-c:a", "libvorbis", webm_path
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
    finally:
        if textfile_path and os.path.exists(textfile_path):
            safe_delete_file(textfile_path)

    return True


# ─────────────────────────────────────────────
#  BACKEND NOTIFICATION (no direct DB access)
# ─────────────────────────────────────────────

def submit_assignment_status(individual_assignment_id, step_code):
    """
    Marks the assignment Submitted via Shot Tracker's unauthenticated
    launcher endpoint. Never touches the database directly.
    """
    step_name = ASSIGNMENT_STEP_NAME_MAP.get(step_code) if step_code else None
    payload = {
        "individual_assignment_id": int(individual_assignment_id),
        "status": "Submitted",
    }
    if step_name:
        payload["step_name"] = step_name

    try:
        resp = requests.post(
            f"{SHOT_TRACKER_URL}/classes/api/launcher/submit-assignment",
            json=payload,
            timeout=10
        )
        print(f"[HTTP] submit-assignment -> {resp.status_code}: {resp.text[:200]}")
        return resp.status_code == 200
    except Exception as e:
        print(f"[WARN] Could not notify backend: {e}")
        return False


# ─────────────────────────────────────────────
#  ASSIGNMENT PLAYBLAST
# ─────────────────────────────────────────────

def perform_playblast(width, height, personal_only=False):
    global audio_checkbox

    current_path = cmds.file(q=True, sn=True)
    if not current_path:
        cmds.warning("Please save the scene before playblasting.")
        return

    filename = os.path.basename(current_path)
    meta = get_scene_metadata()

    if not meta["class_name"] or not meta["assignment_name"] or not meta["individual_assignment_id"]:
        cmds.warning(
            "This scene is missing GAA metadata (it wasn't created or opened by "
            "the current Assignments tool). Open it via the OPEN button on the "
            "Shot Tracker dashboard so it gets tagged automatically."
        )
        return

    name_no_ext = os.path.splitext(filename)[0]
    version_match = re.search(r"_(v\d+)$", name_no_ext, re.IGNORECASE)
    version = version_match.group(1).lower() if version_match else "v1"

    step_code = get_selected_step_code()
    step_suffix = f"_{step_code}" if step_code else ""
    playblast_name = f"{meta['assignment_name']}_{meta['display_name']}{step_suffix}_{version}"
    burn_in_text = _build_burn_in_text(step_code, meta["display_name"], meta["assignment_name"])

    temp_dir = "C:/Temp/Playblast"
    os.makedirs(temp_dir, exist_ok=True)
    avi_path = os.path.join(temp_dir, f"{playblast_name}.avi")
    webm_path = os.path.join(temp_dir, f"{playblast_name}.webm")

    panel = cmds.getPanel(withFocus=True)
    if not cmds.modelPanel(panel, exists=True):
        panel = "modelPanel4"

    orig_nurbs = cmds.modelEditor(panel, q=True, nurbsCurves=True)
    cmds.modelEditor(panel, e=True, nurbsCurves=False)

    sound_node = None
    try:
        if audio_checkbox and cmds.checkBox(audio_checkbox, q=True, value=True):
            sound_node = cmds.timeControl("timeControl1", q=True, sound=True)
    except Exception as e:
        print(f"[AUDIO WARNING] Could not get audio: {e}")

    try:
        cmds.currentUnit(time="film")
        cmds.playblast(
            format="avi",
            filename=avi_path,
            width=width,
            height=height,
            percent=50,
            showOrnaments=False,
            quality=70,
            viewer=False,
            forceOverwrite=True,
            sound=sound_node
        )
        cmds.inViewMessage(amg=f"<hl>Playblast complete</hl>: {avi_path}", pos="topCenter", fade=True)
    except Exception as e:
        cmds.warning(f"Playblast failed: {e}")
        return
    finally:
        cmds.modelEditor(panel, e=True, nurbsCurves=orig_nurbs)

    try:
        if not convert_to_webm(avi_path, webm_path, burn_in_text=burn_in_text):
            return

        safe_delete_file(avi_path)

        if personal_only:
            movies_dir = "C:/Cincy/Movies"
            os.makedirs(movies_dir, exist_ok=True)
            dest_path = os.path.join(movies_dir, f"{playblast_name}.webm")
            shutil.copyfile(webm_path, dest_path)
            cmds.inViewMessage(amg=f"<hl>Saved your movie to:</hl> {dest_path}", pos="topCenter", fade=True)
            return

        output_folder = get_class_output_folder(meta["semester"], meta["class_name"])
        if not output_folder or not os.path.isdir(output_folder):
            cmds.warning(f"No valid output folder found for class: {meta['class_name']}")
            return

        dest_path = os.path.join(output_folder, f"{playblast_name}.webm")
        dest_path = get_next_versioned_path(dest_path)
        if not dest_path:
            cmds.warning("Version bump canceled or failed.")
            return

        shutil.copyfile(webm_path, dest_path)
        cmds.inViewMessage(amg=f"<hl>Copied to:</hl> {dest_path}", pos="topCenter", fade=True)

        if submit_assignment_status(meta["individual_assignment_id"], step_code):
            cmds.inViewMessage(amg="<hl>Submitted for grading</hl>", pos="topCenter", fade=True)
        else:
            cmds.warning("Copied to server, but could not notify Shot Tracker. Your instructor may not see this submission yet — contact them if it doesn't show up.")

    except subprocess.CalledProcessError as e:
        cmds.warning(f"WebM conversion failed: {e}")
    except Exception as e:
        cmds.warning(f"Unexpected error: {e}")


# ─────────────────────────────────────────────
#  FILM PLAYBLAST
# ─────────────────────────────────────────────

def perform_film_playblast(width, height):
    current_path = cmds.file(q=True, sn=True)
    if not current_path:
        cmds.warning("Please save the scene before playblasting.")
        return

    directory, filename = os.path.split(current_path)
    name_no_ext = os.path.splitext(filename)[0]

    parts = name_no_ext.rsplit("_", 5)
    if len(parts) != 6 or not parts[-1].lower().startswith("v"):
        cmds.warning("Filename must follow: Title_Scene_Shot_STEP_User_v#.mb")
        return

    film_title, scene, shot, step, user, version = parts
    step = step.upper()

    if step not in FILM_STEP_CODES:
        cmds.warning(f"Unknown film step '{step}'. Expected one of: {', '.join(FILM_STEP_CODES)}")
        return

    playblast_name = f"{film_title}_{scene}_{shot}_{step}_{user}_{version}"

    temp_dir = "C:/Temp/Playblast"
    os.makedirs(temp_dir, exist_ok=True)
    avi_path = os.path.join(temp_dir, f"{playblast_name}.avi")
    webm_path = os.path.join(temp_dir, f"{playblast_name}.webm")

    panel = cmds.getPanel(withFocus=True)
    if not cmds.modelPanel(panel, exists=True):
        panel = "modelPanel4"

    orig_nurbs = cmds.modelEditor(panel, q=True, nurbsCurves=True)
    cmds.modelEditor(panel, e=True, nurbsCurves=False)

    try:
        cmds.currentUnit(time="film")
        cmds.playblast(
            format="avi",
            filename=avi_path,
            width=width,
            height=height,
            percent=50,
            showOrnaments=False,
            quality=70,
            viewer=False,
            forceOverwrite=True
        )
        cmds.inViewMessage(amg=f"<hl>Playblast complete</hl>: {avi_path}", pos="topCenter", fade=True)
    except Exception as e:
        cmds.warning(f"Playblast failed: {e}")
        return
    finally:
        cmds.modelEditor(panel, e=True, nurbsCurves=orig_nurbs)

    if not shutil.which("ffmpeg"):
        cmds.confirmDialog(
            title="FFmpeg Not Found",
            message="FFmpeg must be installed to export .webm files.",
            button=["OK"]
        )
        return

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", avi_path,
                "-c:v", "libvpx-vp9",
                "-b:v", "2M",
                "-g", "1",
                "-auto-alt-ref", "0",
                "-cpu-used", "4",
                "-vf", "fps=24,setpts=N/24/TB",
                "-c:a", "libvorbis", webm_path,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        cmds.inViewMessage(amg=f"<hl>WebM created</hl>: {webm_path}", pos="topCenter", fade=True)

        output_folder = directory
        dest_path = os.path.join(output_folder, f"{playblast_name}.webm")
        dest_path = get_next_versioned_path(dest_path)
        if not dest_path:
            cmds.warning("Version bump canceled or failed.")
            return

        shutil.copyfile(webm_path, dest_path)
        print(f"[OK] Copied to versioned destination: {dest_path}")

        final_version_match = re.search(r"_v(\d+)", dest_path)
        final_version = final_version_match.group(1) if final_version_match else version.lstrip("vV")

        hud_text = f"{film_title}-{scene}-{shot}-{step}-{user}-v{final_version}"
        hud_filter = (
            f"drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':"
            f"text='{hud_text}':"
            f"x=(w-text_w)-20:y=h-(text_h+50):"
            f"fontsize=14:fontcolor=white:borderw=2:"
            f"box=1:boxcolor=black@0.25:boxborderw=12"
        )

        hud_temp = dest_path.replace(".webm", "_HUD.webm")
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", dest_path,
                "-vf", hud_filter,
                "-c:v", "libvpx-vp9", "-b:v", "2M",
                "-c:a", "copy", hud_temp,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        shutil.move(hud_temp, dest_path)

        cmds.inViewMessage(amg=f"<hl>Final Render:</hl> {os.path.basename(dest_path)}", pos="topCenter", fade=True)

        try:
            clean_name = re.sub(r"_[A-Za-z ]+_v\d+$", "", playblast_name)
            gs_resp = requests.get(
                f"{SHOT_TRACKER_URL}/review/get_scene_status",
                params={"file_name": clean_name},
                timeout=10
            )
            step_display_id = gs_resp.json().get("display_step_id") if gs_resp.status_code == 200 else None

            if not step_display_id:
                print("[FAIL] No display_step_id returned — skipping status update.")
            else:
                with open(dest_path, "rb") as f:
                    files = {"file": f}
                    payload = {
                        "film_name": film_title,
                        "scene_number": scene,
                        "shot_number": shot,
                        "step_id": step_display_id,
                    }
                    resp = requests.post(
                        f"{SHOT_TRACKER_URL}/review/upload_film_shot",
                        files=files,
                        data=payload,
                        timeout=20
                    )
                if resp.status_code == 200:
                    cmds.inViewMessage(
                        amg=f"<hl>Submitted:</hl> {film_title}_{scene}_{shot} (v{final_version})",
                        pos="topCenter",
                        fade=True
                    )
                else:
                    print(f"[WARN] upload_film_shot failed -> {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[EXCEPTION] Status update failed: {e}")
            cmds.warning("Could not update status — server may be offline.")

        safe_delete_file(avi_path)

    except Exception as e:
        cmds.warning(f"WebM conversion failed: {e}")


# ─────────────────────────────────────────────
#  UI
# ─────────────────────────────────────────────

def show_ffmpeg_help(*args):
    cmds.confirmDialog(
        title="Install FFmpeg",
        message=(
            "To export .webm files, FFmpeg must be installed.\n\n"
            "1. Go to: https://ffmpeg.org/download.html\n"
            "2. Download the Windows/macOS version\n"
            "3. Add the FFmpeg /bin folder to your system PATH\n\n"
            "Ask your instructor or admin for help if unsure."
        ),
        button=["OK"]
    )


def show_help(*args):
    cmds.confirmDialog(
        title="Help",
        message=(
            "GAA Playblast Tool\n\n"
            "ASSIGNMENTS\n"
            "1. The name of your file is shown at the top of the window.\n"
            "2. If an audio track is found, check Include Audio.\n"
            "3. Choose which movie to create:\n"
            "   a. SUBMIT ASSIGNMENT - submits for grading.\n"
            "   b. MOVIE FOR YOU - saves a personal copy only, does not submit.\n\n"
            "FILM SHOTS\n"
            "1. The name of your file is shown at the top of the window.\n"
            "2. If an audio track is found, check Include Audio.\n"
            "3. Choose which movie to create:\n"
            "   a. SUBMIT SHOT - submits for review.\n"
            "   b. MOVIE FOR YOU - saves a personal copy only.\n\n"
            "Ask your instructor or admin for help if unsure."
        ),
        button=["OK"]
    )


def launch_playblast_ui():
    global audio_checkbox, step_menu

    if cmds.window("gaaPlayblastWin", exists=True):
        cmds.deleteUI("gaaPlayblastWin")

    current_path = cmds.file(q=True, sn=True)
    filename = os.path.basename(current_path).strip() if current_path else ""
    is_film = is_film_scene(filename)
    meta = get_scene_metadata() if not is_film else None
    is_assign = bool(meta and meta["class_name"] and meta["assignment_name"]) if not is_film else False

    win = cmds.window("gaaPlayblastWin", title="Playblast Tool", widthHeight=(260, 320))
    cmds.columnLayout(adjustableColumn=True, rowSpacing=10)

    cmds.text(label=f"Scene: {filename or '[Not Saved]'}", align="center")

    sound_node = cmds.timeControl("timeControl1", q=True, sound=True)
    has_audio = bool(sound_node)
    if has_audio:
        audio_checkbox = cmds.checkBox(label="Include Audio", value=True)
    else:
        cmds.text(label="No audio track found.", align="center")
        audio_checkbox = cmds.checkBox(label="Include Audio", value=False, enable=False)

    cmds.separator(style="in")

    # Whether this specific assignment actually uses Planning/Blocking/Polish
    # phases isn't known without a database query, which this tool
    # deliberately avoids. Just leave the override available for any
    # assignment scene — nothing breaks if a student leaves it unchecked.
    has_step_phases = is_assign

    cmds.checkBox(
        "enableStepCheckbox",
        label="Override Step",
        value=False,
        enable=has_step_phases,
        changeCommand=toggle_step_menu
    )

    cmds.text(label="Step:", align="center")
    step_menu = cmds.optionMenu(enable=False)
    for label in STEP_CODES:
        cmds.menuItem(label=label)

    cmds.separator(style="in")

    if is_assign:
        cmds.button(label="SUBMIT ASSIGNMENT", command=lambda _: perform_playblast(1920, 1080))
        cmds.button(label="MOVIE FOR YOU", command=lambda _: perform_playblast(960, 540, personal_only=True))
    elif is_film:
        cmds.button(label="SUBMIT SHOT", command=lambda _: perform_film_playblast(1920, 1080))
        cmds.button(label="MOVIE FOR YOU", command=lambda _: perform_film_playblast(960, 540))
    else:
        cmds.text(label="Unrecognized file format", align="center")
        cmds.text(label="Open your scene via Shot Tracker's", align="center")
        cmds.text(label="OPEN button first.", align="center")

    cmds.separator(style="in", height=8)
    cmds.button(label="How to Install FFmpeg", command=show_ffmpeg_help)
    cmds.button(label="Help", command=show_help)

    cmds.setParent("..")
    cmds.showWindow(win)


def run():
    launch_playblast_ui()


if __name__ == "__main__":
    run()
