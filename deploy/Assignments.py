# Assignments.py
# UC GAA Shot Tracker — silent Maya assignment setup + shared save/open logic
# Invoked by the GAA shelf (inside Maya/mayapy) after launcher.py has written
# the session context. Loads the correct rig(s), optional camera, and frame
# range for the student's active assignment, then saves a fresh scene to the
# class's network Assignments folder.
#
# run() itself stays silent: no dialogs, no prompts. Every failure is logged
# and the function returns False rather than raising or exiting the host
# Maya session. The step/lock helpers below are shared with GAASave.py and
# GAAOpen.py, which are the ones that show PySide6 prompts -- this module is
# the one place that knows how to talk to Shot Tracker and version/create
# scene files, so those two tools stay thin UI layers over it.

import os
import re
import json
import getpass
import datetime
import requests

import maya.cmds as cmds

# ── Config ────────────────────────────────────────────────────
SESSIONS_PATH     = r"C:\Cincy\sessions"
CONFIG_PATH       = r"C:\Cincy\Configs\assignments_config.json"
LOG_DIR           = r"C:\Cincy\logs"
CLASS_FOLDER_ROOT = r"\\gaaap1prd01w.ad.uc.edu\Classes"
SHOT_TRACKER_URL  = os.environ.get("SHOT_TRACKER_URL", "http://10.23.20.210:8000")

# Steps that actually get their own Maya scene file. Matches
# GAAPlayblastTool_V7.STEP_CODES exactly (Blocking/Blocking Plus/Polish) --
# Planning has a step_codes entry ("PL") for other purposes but no
# corresponding .ma file, so it's deliberately excluded from file/version
# derivation.
FILE_VERSIONED_STEP_CODES = {"BL", "BP", "P"}

_log_file = None


# ── Logging ───────────────────────────────────────────────────
def _init_log():
    global _log_file
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_file = os.path.join(LOG_DIR, f"assignments_{timestamp}.log")


def log(message):
    if _log_file is None:
        _init_log()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    try:
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


# ── Session context ───────────────────────────────────────────
def load_session_context(login_name):
    session_file = os.path.join(SESSIONS_PATH, f"{login_name}_context.json")
    if not os.path.isfile(session_file):
        log(f"ERROR: Session context not found: {session_file}")
        return None
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"ERROR: Could not read session context {session_file}: {e}")
        return None


def resolve_assignment(context, individual_assignment_id=None):
    """
    Picks the assignment dict to act on: explicit individual_assignment_id,
    else the launcher's active_assignment_id, else the sole assignment if
    there is exactly one.
    """
    assignments = context.get("assignments", [])
    if not assignments:
        log("ERROR: Session context has no assignments")
        return None

    target_id = individual_assignment_id or context.get("active_assignment_id")

    if target_id is not None:
        match = next(
            (a for a in assignments if str(a["individual_assignment_id"]) == str(target_id)),
            None
        )
        if not match:
            log(f"ERROR: individual_assignment_id={target_id} not found in session context")
            return None
        return match

    if len(assignments) == 1:
        return assignments[0]

    log("ERROR: No individual_assignment_id given/active and multiple assignments in context; cannot pick one")
    return None


def resolve_scene_context(login_name=None):
    """
    Returns (context, assignment, login_name) for whatever assignment the
    CURRENT scene belongs to, or (None, None, None) if it can't be
    determined (no dialogs shown here -- callers like GAASave.py/GAAOpen.py
    own that). Prefers the scene's own GAA_individual_assignment_id tag
    (stamped by this module on every scene it creates/opens) over the
    session's active_assignment_id/sole-assignment fallback, so a tool
    always acts on whichever assignment this specific scene actually
    belongs to -- not whatever the launcher happened to point at most
    recently for this OS login.
    """
    login_name = login_name or getpass.getuser()
    context = load_session_context(login_name)
    if not context:
        return None, None, None

    tagged_id = cmds.fileInfo("GAA_individual_assignment_id", q=True)
    tagged_id = tagged_id[0] if tagged_id else None

    assignment = resolve_assignment(context, tagged_id)
    if not assignment:
        return None, None, None

    return context, assignment, login_name


# ── Frame range (assignments_config.json) ────────────────────
def load_frame_range(class_name, assignment_name):
    if not os.path.isfile(CONFIG_PATH):
        log(f"ERROR: assignments_config.json not found at {CONFIG_PATH}")
        return None, None

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        log(f"ERROR: Could not read assignments_config.json: {e}")
        return None, None

    entry = config.get("semester", {}).get(class_name, {}).get(assignment_name)
    if not entry:
        log(f"ERROR: No config entry for class '{class_name}' / assignment '{assignment_name}' in assignments_config.json")
        return None, None

    frame_start = entry.get("frame_start")
    frame_end = entry.get("frame_end")
    if frame_start is None or frame_end is None:
        log(f"ERROR: frame_start/frame_end not set for '{class_name}' / '{assignment_name}' in assignments_config.json")
        return None, None

    return frame_start, frame_end


# ── Naming helpers ────────────────────────────────────────────
def sanitize_namespace(name):
    ns = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_")
    if not ns:
        ns = "rig"
    if ns[0].isdigit():
        ns = "_" + ns
    return ns


def unique_namespace(base, used):
    ns = base
    i = 2
    while ns in used:
        ns = f"{base}_{i}"
        i += 1
    used.add(ns)
    return ns


def build_save_dir(semester, class_name):
    return os.path.join(CLASS_FOLDER_ROOT, semester, class_name, "Assignments", "Scenes")


def find_latest_scene(save_dir, base_name):
    """
    Returns (version, path) for the highest existing version of this
    student's scene under the flat, step-agnostic convention
    ({base}_v{N}.ma), or (0, None) if none exist yet.
    """
    pattern = re.compile(rf"^{re.escape(base_name)}_v(\d+)\.ma$", re.IGNORECASE)
    highest = 0
    highest_path = None
    try:
        for entry in os.listdir(save_dir):
            match = pattern.match(entry)
            if match:
                version = int(match.group(1))
                if version > highest:
                    highest = version
                    highest_path = os.path.join(save_dir, entry)
    except OSError as e:
        log(f"WARNING: Could not list {save_dir} for version scan: {e}")
    return highest, highest_path


def find_latest_step_scene(save_dir, base_name, step_code):
    """
    Same idea as find_latest_scene, but scoped to one step's own version
    family: {base_name}_{step_code}_V###.ma. A pre-step-versioning file
    like {base_name}_v3.ma simply won't match this pattern, so it's
    correctly invisible here without any special-case handling -- that's
    also what makes "version resets to V001 at the start of each new step"
    true for free: each step_code's scan starts from zero found files.
    """
    pattern = re.compile(
        rf"^{re.escape(base_name)}_{re.escape(step_code)}_V(\d+)\.ma$",
        re.IGNORECASE
    )
    highest = 0
    highest_path = None
    try:
        for entry in os.listdir(save_dir):
            match = pattern.match(entry)
            if match:
                version = int(match.group(1))
                if version > highest:
                    highest = version
                    highest_path = os.path.join(save_dir, entry)
    except OSError as e:
        log(f"WARNING: Could not list {save_dir} for step version scan: {e}")
    return highest, highest_path


# ── Step / lock API (shared with GAASave.py, GAAOpen.py) ─────
def fetch_steps_status(individual_assignment_id):
    """
    Live lock/step state from Shot Tracker for one individual assignment.
    Returns None (not []) on any failure to fetch, so callers can tell
    "server unreachable" apart from "assignment genuinely has no steps".
    """
    try:
        r = requests.get(
            f"{SHOT_TRACKER_URL}/classes/api/launcher/steps/status",
            params={"individual_assignment_id": individual_assignment_id},
            timeout=10
        )
        r.raise_for_status()
        return r.json().get("steps", [])
    except Exception as e:
        log(f"ERROR: Could not fetch step status: {e}")
        return None


def resolve_current_step(steps):
    """
    Returns the step Save/Open/Lock should act on:
      - the current file-versioned step (Blocking/Blocking Plus/Polish --
        lowest order_num unlocked, or the last one if every one of them
        is locked), if this assignment has any; else
      - the sole non-FB/Grade step for the simpler single-step workflow
        (e.g. "Basic Assignment") -- locking still applies to it, it just
        has no short_code so filenames stay on the flat convention.
    Returns None only if steps is empty, or has more than one step but
    none of them are file-versioned (an unexpected/ambiguous shape).
    """
    if not steps:
        return None

    file_steps = [s for s in steps if s.get("short_code") in FILE_VERSIONED_STEP_CODES]
    if file_steps:
        unlocked = [s for s in file_steps if not s["locked"]]
        if unlocked:
            return min(unlocked, key=lambda s: s["order_num"])
        return max(file_steps, key=lambda s: s["order_num"])

    if len(steps) == 1:
        return steps[0]

    return None


def find_carry_forward_source(steps, current_step, save_dir, base_name):
    """
    For a current step that has no file of its own yet, finds the
    highest-order prior file-versioned step that does have an existing
    file, so the new step can continue from it (Blocking Plus/Polish
    refine the previous pass, they don't re-reference rigs from scratch).
    Returns (step, version, path), or (None, None, None) if no earlier
    step has anything saved (a genuinely brand-new assignment).
    """
    candidates = sorted(
        (s for s in steps
         if s.get("short_code") in FILE_VERSIONED_STEP_CODES
         and s["order_num"] < current_step["order_num"]),
        key=lambda s: s["order_num"],
        reverse=True
    )
    for s in candidates:
        version, path = find_latest_step_scene(save_dir, base_name, s["short_code"])
        if path:
            return s, version, path
    return None, None, None


def lock_step(individual_assignment_id, step_name, login_name):
    try:
        r = requests.post(
            f"{SHOT_TRACKER_URL}/classes/api/launcher/steps/lock",
            json={
                "individual_assignment_id": individual_assignment_id,
                "step_name": step_name,
                "login_name": login_name
            },
            timeout=10
        )
        return r.status_code == 200, (r.json() if r.content else {})
    except Exception as e:
        log(f"ERROR: Could not lock step: {e}")
        return False, {"error": str(e)}


def unlock_step(individual_assignment_id, step_name, login_name):
    try:
        r = requests.post(
            f"{SHOT_TRACKER_URL}/classes/api/launcher/steps/unlock",
            json={
                "individual_assignment_id": individual_assignment_id,
                "step_name": step_name,
                "login_name": login_name
            },
            timeout=10
        )
        return r.status_code == 200, (r.json() if r.content else {})
    except Exception as e:
        log(f"ERROR: Could not unlock step: {e}")
        return False, {"error": str(e)}


# ── Maya scene operations ────────────────────────────────────
def reference_rigs(rigs):
    used_namespaces = set()
    for rig in rigs:
        rig_path = rig.get("path") if isinstance(rig, dict) else rig
        if not rig_path:
            continue
        if not os.path.isfile(rig_path):
            log(f"ERROR: Rig not found on disk: {rig_path}")
            continue

        base = sanitize_namespace(os.path.splitext(os.path.basename(rig_path))[0])
        ns = unique_namespace(base, used_namespaces)

        cmds.file(rig_path, reference=True, namespace=ns, ignoreVersion=True)
        log(f"Referenced rig: {rig_path} (namespace={ns})")


def add_camera(assignment_name):
    base = sanitize_namespace(assignment_name) + "_cam"
    cam_transform, _ = cmds.camera(name=base)
    cmds.xform(cam_transform, worldSpace=True, translation=(0, 30, 90))
    log(f"Created camera: {cam_transform} at (0, 30, 90)")

    set_four_view_layout(cam_transform)

    return cam_transform


def set_four_view_layout(camera_name):
    """
    Switches the viewport to Maya's "Four View" panel layout and assigns
    top-left=top, top-right=camera_name, bottom-left=front,
    bottom-right=persp.

    Each panel's on-screen position is determined from its actual Qt
    widget geometry rather than assumed from Maya's internal panel-name
    ordering (which isn't consistently documented/guaranteed across
    versions), so the top-left/top-right/bottom-left/bottom-right
    assignment is correct regardless of whichever default camera Maya's
    own Four View layout happens to put in each quadrant. No-op in
    batch/mayapy -- there's no viewport to lay out.

    NOTE: the exact saved-layout name passed to setNamedPanelLayout
    ("Four View") is my best-effort guess based on long-standing Maya
    convention -- I don't have an interactive Maya session to verify it
    against this specific 2026 build. If this warns instead of laying out
    the viewport, that string is the first thing to check.
    """
    if cmds.about(batch=True):
        return

    try:
        from maya import mel
        import maya.OpenMayaUI as omui
        from PySide6 import QtWidgets
        import shiboken6

        mel.eval('setNamedPanelLayout("Four View")')

        model_panels = [
            p for p in (cmds.getPanel(visiblePanels=True) or [])
            if cmds.getPanel(typeOf=p) == "modelPanel"
        ]

        positioned = []
        for panel in model_panels:
            ctrl_ptr = omui.MQtUtil.findControl(panel)
            if not ctrl_ptr:
                continue
            widget = shiboken6.wrapInstance(int(ctrl_ptr), QtWidgets.QWidget)
            top_left = widget.mapToGlobal(widget.rect().topLeft())
            positioned.append((top_left.y(), top_left.x(), panel))

        if len(positioned) != 4:
            log(f"WARNING: expected 4 visible model panels for Four View layout, found {len(positioned)}")
            return

        # Sorting by (y, x) groups the two smaller-y (top row) panels
        # first, ordered left-to-right, then the two larger-y (bottom row)
        # panels, also left-to-right.
        positioned.sort()
        top_left_panel = positioned[0][2]
        top_right_panel = positioned[1][2]
        bottom_left_panel = positioned[2][2]
        bottom_right_panel = positioned[3][2]

        cmds.modelEditor(top_left_panel, edit=True, camera="top")
        cmds.modelEditor(top_right_panel, edit=True, camera=camera_name)
        cmds.modelEditor(bottom_left_panel, edit=True, camera="front")
        cmds.modelEditor(bottom_right_panel, edit=True, camera="persp")

        log(f"Four View layout set: top-left=top, top-right={camera_name}, bottom-left=front, bottom-right=persp")
    except Exception as e:
        log(f"WARNING: Could not set Four View layout: {e}")


def open_existing_scene(path):
    """
    Opens a previously-saved scene as-is. Maya's cmds.file(open=True) raises
    RuntimeError for non-fatal warnings during the read (e.g. a missing
    renderer plugin like Arnold leaving unresolved attributes on default
    cameras) even though the scene content still loads fully — the
    interactive File > Open menu shows the same warnings but doesn't treat
    them as failures. Match that tolerant behavior here, and explicitly
    re-bind the filename afterward in case the interrupted read left the
    scene open without it.
    """
    try:
        cmds.file(path, open=True, force=True, ignoreVersion=True)
    except RuntimeError as e:
        log(f"WARNING: Non-fatal errors while opening {path}: {e}")
        cmds.file(rename=path)


def set_frame_range(frame_start, frame_end):
    cmds.playbackOptions(
        minTime=frame_start,
        maxTime=frame_end,
        animationStartTime=frame_start,
        animationEndTime=frame_end
    )
    log(f"Frame range set: {frame_start}-{frame_end}")


def stamp_scene_metadata(class_name, assignment_name, individual_assignment_id, semester, display_name):
    """
    Tags the scene with fileInfo so downstream tools (the playblast tool,
    GAASave.py, GAAOpen.py) can identify class/assignment/semester/student
    straight from the scene itself — no filename parsing, no direct
    database access from Maya required.
    """
    cmds.fileInfo("GAA_class", class_name)
    cmds.fileInfo("GAA_assignment", assignment_name)
    cmds.fileInfo("GAA_individual_assignment_id", str(individual_assignment_id))
    cmds.fileInfo("GAA_semester", semester)
    cmds.fileInfo("GAA_display_name", display_name)


def save_scene(save_path):
    """
    No explicit type= on the save -- Maya infers mayaAscii from the .ma
    extension just set by rename(), same as a plain File > Save does.
    An explicit type="mayaAscii" here instead makes Maya treat this as a
    declared format-change request, which it refuses outright on a scene
    containing "unknown" node data (typically from a referenced rig built
    with a plugin outside pluginPrefs.mel's autoload list) -- confirmed on
    a lab machine: plain Save succeeded on such a scene, this explicit-type
    save didn't.
    """
    save_dir = os.path.dirname(save_path)
    os.makedirs(save_dir, exist_ok=True)
    cmds.file(rename=save_path)
    cmds.file(save=True, force=True)
    log(f"Scene saved: {save_path}")


def create_or_continue_step(steps, current_step, save_dir, base_name, class_name,
                             assignment_name, assignment, semester, display_name,
                             individual_assignment_id):
    """
    Creates the first file for current_step (must be file-versioned --
    has a short_code). Continues from the highest-order prior
    file-versioned step's latest file if one exists, so Blocking Plus/
    Polish refine the previous pass instead of starting blank; otherwise
    builds a genuinely fresh scene (rig references, camera, frame range)
    exactly like a brand-new assignment.

    Returns (True, save_path) on success, or (False, None) on failure
    (already logged).
    """
    step_code = current_step["short_code"]
    prev_step, prev_version, prev_path = find_carry_forward_source(steps, current_step, save_dir, base_name)

    if prev_path:
        open_existing_scene(prev_path)
        save_path = os.path.join(save_dir, f"{base_name}_{step_code}_V001.ma")
        stamp_scene_metadata(class_name, assignment_name, individual_assignment_id, semester, display_name)
        save_scene(save_path)
        log(f"Carried into {current_step['name']} from {prev_step['name']} V{prev_version:03d}: {save_path}")
        return True, save_path

    frame_start, frame_end = load_frame_range(class_name, assignment_name)
    if frame_start is None or frame_end is None:
        return False, None

    cmds.file(new=True, force=True)
    reference_rigs(assignment.get("rigs", []))
    if assignment.get("camera"):
        add_camera(assignment_name)
    set_frame_range(frame_start, frame_end)
    stamp_scene_metadata(class_name, assignment_name, individual_assignment_id, semester, display_name)

    save_path = os.path.join(save_dir, f"{base_name}_{step_code}_V001.ma")
    save_scene(save_path)
    log(f"Created fresh scene for {current_step['name']}: {save_path}")
    return True, save_path


def find_next_step(steps, current_step):
    """
    The file-versioned step (Blocking/Blocking Plus/Polish) immediately
    after current_step by order_num, or None if current_step is already
    the last one -- e.g. locking Polish has nothing further to advance
    into. Planning is never a candidate here even if it sits at a lower
    order_num than current_step, since it isn't part of the
    Blocking/Blocking Plus/Polish file family (see FILE_VERSIONED_STEP_CODES).
    """
    candidates = sorted(
        (s for s in steps
         if s.get("short_code") in FILE_VERSIONED_STEP_CODES
         and s["order_num"] > current_step["order_num"]),
        key=lambda s: s["order_num"]
    )
    return candidates[0] if candidates else None


def open_or_create_step(steps, step, save_dir, base_name, class_name, assignment_name,
                         assignment, semester, display_name, individual_assignment_id):
    """
    Opens step's latest file if one already exists, otherwise creates it.
    Safe to call with any step, file-versioned or not -- a
    non-file-versioned step (no short_code, the simpler single-step
    workflow) falls back to the flat convention with a fresh-scene build,
    since create_or_continue_step's carry-forward logic assumes a
    short_code to key its filename on.

    Shared by GAASave.py (advancing into the next step right after a lock)
    and GAAOpen.py (opening whichever step the user picked), so both tools
    agree on this behavior instead of each re-implementing the
    file-exists-or-not branch separately.

    Returns (success, action, path) where action is "opened" or "created"
    (None on failure, already logged).
    """
    is_file_versioned = step["short_code"] in FILE_VERSIONED_STEP_CODES

    if is_file_versioned:
        version, path = find_latest_step_scene(save_dir, base_name, step["short_code"])
    else:
        version, path = find_latest_scene(save_dir, base_name)

    if path:
        open_existing_scene(path)
        stamp_scene_metadata(class_name, assignment_name, individual_assignment_id, semester, display_name)
        return True, "opened", path

    if not is_file_versioned:
        frame_start, frame_end = load_frame_range(class_name, assignment_name)
        if frame_start is None or frame_end is None:
            return False, None, None
        cmds.file(new=True, force=True)
        reference_rigs(assignment.get("rigs", []))
        if assignment.get("camera"):
            add_camera(assignment_name)
        set_frame_range(frame_start, frame_end)
        stamp_scene_metadata(class_name, assignment_name, individual_assignment_id, semester, display_name)
        save_path = os.path.join(save_dir, f"{base_name}_v1.ma")
        save_scene(save_path)
        log(f"Created fresh scene: {save_path}")
        return True, "created", save_path

    success, save_path = create_or_continue_step(
        steps, step, save_dir, base_name, class_name, assignment_name,
        assignment, semester, display_name, individual_assignment_id
    )
    return success, ("created" if success else None), save_path


def register_gaa_save_hotkey():
    """
    Binds Alt+S to GAASave.save_silent() on every successful run() -- the
    Alt+S shortcut isn't managed by the installer (no hotkeys.mhk mirrored
    anywhere in Install_UC_TOOLS_FALL_2026.bat), so it's self-registered
    here at runtime instead of via userSetup.mel, which stays untouched.
    Registration is idempotent, so re-running this on every launch is fine.
    """
    try:
        import GAASave
        GAASave.register_hotkey()
    except Exception as e:
        log(f"WARNING: Could not register GAA Save hotkey: {e}")


# ── Main (silent, launcher-triggered) ─────────────────────────
def run(login_name=None, individual_assignment_id=None):
    _init_log()
    log("=" * 50)
    log("Assignments.py started")

    login_name = login_name or getpass.getuser()
    log(f"login_name={login_name} individual_assignment_id={individual_assignment_id}")

    try:
        context = load_session_context(login_name)
        if not context:
            return False

        assignment = resolve_assignment(context, individual_assignment_id)
        if not assignment:
            return False

        class_name = context["class"]["name"]
        semester = context["class"].get("semester")
        display_name = context["user"]["display_name"]
        assignment_name = assignment["name"]
        ia_id = assignment["individual_assignment_id"]

        if not semester:
            log("ERROR: Session context has no class.semester")
            return False

        log(f"Assignment: {assignment_name} | class: {class_name} | semester: {semester}")

        save_dir = build_save_dir(semester, class_name)
        base_name = f"{assignment['filename']}_{display_name}"

        steps = fetch_steps_status(ia_id)
        current_step = resolve_current_step(steps) if steps is not None else None

        if current_step is None:
            if steps is None:
                log("WARNING: Could not fetch step status; falling back to flat versioning")
            else:
                log("WARNING: Could not resolve an acting step; falling back to flat versioning")
            return _run_flat(class_name, assignment_name, assignment, semester, display_name, save_dir, base_name, ia_id)

        if current_step["short_code"] not in FILE_VERSIONED_STEP_CODES:
            # Simple single-step workflow (e.g. "Basic Assignment") -- no
            # Blocking/Blocking Plus/Polish to version by. Locking still
            # applies to this sole step via GAA Save/Open's lock actions,
            # it's just not reflected in the filename.
            return _run_flat(class_name, assignment_name, assignment, semester, display_name, save_dir, base_name, ia_id)

        existing_version, existing_path = find_latest_step_scene(save_dir, base_name, current_step["short_code"])

        if existing_path:
            open_existing_scene(existing_path)
            stamp_scene_metadata(class_name, assignment_name, ia_id, semester, display_name)
            log(f"Opened existing {current_step['name']} scene (V{existing_version:03d}): {existing_path}")
            register_gaa_save_hotkey()
            log("Assignments.py completed successfully")
            return True

        success, _ = create_or_continue_step(
            steps, current_step, save_dir, base_name, class_name,
            assignment_name, assignment, semester, display_name, ia_id
        )
        if not success:
            return False

        register_gaa_save_hotkey()
        log("Assignments.py completed successfully")
        return True

    except Exception as e:
        log(f"ERROR: Unhandled exception: {e}")
        return False


def _run_flat(class_name, assignment_name, assignment, semester, display_name, save_dir, base_name, individual_assignment_id):
    """
    The original step-agnostic flow: {base}_v{N}.ma, one continuous
    version counter. Used when Shot Tracker's step-status endpoint is
    unreachable, or the assignment's workflow has no Blocking/Blocking
    Plus/Polish steps to version by.
    """
    existing_version, existing_path = find_latest_scene(save_dir, base_name)

    if existing_path:
        open_existing_scene(existing_path)
        stamp_scene_metadata(class_name, assignment_name, individual_assignment_id, semester, display_name)
        log(f"Opened existing scene (v{existing_version}): {existing_path}")
        register_gaa_save_hotkey()
        log("Assignments.py completed successfully")
        return True

    frame_start, frame_end = load_frame_range(class_name, assignment_name)
    if frame_start is None or frame_end is None:
        return False

    cmds.file(new=True, force=True)
    reference_rigs(assignment.get("rigs", []))
    if assignment.get("camera"):
        add_camera(assignment_name)
    set_frame_range(frame_start, frame_end)
    stamp_scene_metadata(class_name, assignment_name, individual_assignment_id, semester, display_name)

    save_path = os.path.join(save_dir, f"{base_name}_v1.ma")
    save_scene(save_path)

    register_gaa_save_hotkey()
    log("Assignments.py completed successfully")
    return True


if __name__ == "__main__":
    import sys
    _login_name = sys.argv[1] if len(sys.argv) > 1 else None
    _individual_assignment_id = sys.argv[2] if len(sys.argv) > 2 else None
    run(login_name=_login_name, individual_assignment_id=_individual_assignment_id)
