# CapstoneBlocking.py
# UC GAA Shot Tracker — silent Maya shot Blocking setup for the capstone
# film pipeline. Invoked by launcher.py (action=shot_blocking) after it has
# written {login_name}_shot_blocking_context.json. Same silent contract as
# the other Capstone*.py modules: no dialogs, no prompts, failures logged
# and returned as False.
#
# Blocking sits between Layout and Animation as its own top-level workflow
# step (Layout -> Blocking -> Animation -> Lighting), NOT as a self-locked
# sub-step of Animation the way an earlier iteration of this pipeline had
# it (Blocking/Blocking Plus/Polish inside CapstoneAnimation.py) -- that
# model has been dropped per explicit product direction. Blocking now works
# exactly like Layout's shot-level flow and Lighting: single continuously
# versioned file, gated on the PRIOR step's per-shot approval, coordinator
# approves this shot individually (matches Layout's shape, not a scene-wide
# or self-lock mechanism).
#
# Filename convention: {film}_{scene:3d}_{shot:3d}_BL_{user}_v{n}.mb --
# distinct step code from Layout (_LAY_) and Animation (_ANIM_) by
# construction, so a Blocking session can never save over a Layout or
# Animation file regardless of what's open in Maya.

import os
import re
import json
import shutil
import getpass
import datetime

import maya.cmds as cmds

# ── Config ────────────────────────────────────────────────────
SESSIONS_PATH = r"C:\Cincy\sessions"
LOG_DIR       = r"C:\Cincy\logs"
FILMS_ROOT    = r"\\GAAAP1PRD01W\Films"

STEP_CODE        = "BL"
LAYOUT_STEP_CODE = "LAY"

# Mirrors CapstoneLayout.py/CapstoneAnimation.py -- duplicated rather than
# imported, deploy/ tools are each self-contained. Used to reference the
# Shot-Ready rig for each of the scene's configured Character/Rigs assets,
# same as Animation's own (now removed) rig-referencing did.
ASSET_ROOT = r"\\GAAAP1PRD01W\Films"
CATEGORY_FOLDER_MAP = {
    "Sets": "Sets",
    "Character/Rigs": "Rigs",
    "Rigs": "Rigs",
    "Props - 3D": "Props_-_3D",
    "Props - 2D": "Props_-_2D",
    "Light Rigs": "LightRigs",
    "BGs": "BGs",
}

_log_file = None


# ── Logging ───────────────────────────────────────────────────
def _init_log():
    global _log_file
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_file = os.path.join(LOG_DIR, f"capstone_blocking_{timestamp}.log")


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
def load_session(login_name):
    session_file = os.path.join(SESSIONS_PATH, f"{login_name}_shot_blocking_context.json")
    if not os.path.isfile(session_file):
        log(f"ERROR: Shot blocking session context not found: {session_file}")
        return None
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"ERROR: Could not read shot blocking session context {session_file}: {e}")
        return None


# ── Naming / path helpers ─────────────────────────────────────
def pad3(number):
    return str(number).zfill(3)


def shot_dir(film_name, scene_number, shot_number):
    return os.path.join(FILMS_ROOT, film_name, pad3(scene_number), pad3(shot_number))


def build_base_name(film_name, scene_number, shot_number, display_name):
    # STEP_CODE ("BL") is always embedded here, so this name can never
    # collide with a "_LAY_" or "_ANIM_" filename in the same folder.
    return f"{film_name}_{pad3(scene_number)}_{pad3(shot_number)}_{STEP_CODE}_{display_name}"


def find_latest_version(directory, base_name):
    """Same convention as CapstoneLayout.find_latest_version()."""
    pattern = re.compile(rf"^{re.escape(base_name)}_v(\d+)\.mb$", re.IGNORECASE)
    highest = 0
    highest_path = None
    try:
        for entry in os.listdir(directory):
            match = pattern.match(entry)
            if match:
                version = int(match.group(1))
                if version > highest:
                    highest = version
                    highest_path = os.path.join(directory, entry)
    except OSError as e:
        log(f"WARNING: Could not list {directory} for version scan: {e}")
    return highest, highest_path


def find_latest_layout_any_user(directory, film_name, scene_number, shot_number):
    """
    Highest {film}_{scene}_{shot}_LAY_*_v{N}.mb in the shot folder --
    same "pick globally highest version, not scoped to a specific user"
    reasoning as CapstoneLayout.find_latest_version_any_user().
    """
    prefix = f"{film_name}_{pad3(scene_number)}_{pad3(shot_number)}_{LAYOUT_STEP_CODE}_"
    pattern = re.compile(rf"^{re.escape(prefix)}.+_v(\d+)\.mb$", re.IGNORECASE)
    highest = 0
    highest_path = None
    try:
        for entry in os.listdir(directory):
            match = pattern.match(entry)
            if match and entry.startswith(prefix):
                version = int(match.group(1))
                if version > highest:
                    highest = version
                    highest_path = os.path.join(directory, entry)
    except OSError as e:
        log(f"WARNING: Could not list {directory} for shot layout scan: {e}")
    return highest, highest_path


def get_asset_production_dir(film_name, category, asset_name):
    folder = CATEGORY_FOLDER_MAP.get(category)
    if not folder:
        return None
    return os.path.join(ASSET_ROOT, film_name, "Assets", folder, asset_name)


def find_latest_rig_version(asset_dir, asset_name):
    """Highest version among files tagged _RIG_ -- the Shot-Ready file, same idea as Assets.py's find_latest_version_for_step()."""
    safe_name = re.escape(asset_name).replace(r"\ ", r"[ _]")
    pattern = re.compile(rf"^{safe_name}_RIG_.*?_v(\d+)\.(ma|mb)$", re.IGNORECASE)

    highest = 0
    highest_path = None
    try:
        for entry in os.listdir(asset_dir):
            match = pattern.match(entry)
            if match:
                version = int(match.group(1))
                if version > highest:
                    highest = version
                    highest_path = os.path.join(asset_dir, entry)
    except OSError as e:
        log(f"WARNING: Could not list {asset_dir} for rig version scan: {e}")
    return highest, highest_path


# ── Maya scene operations ────────────────────────────────────
def sanitize_namespace(name):
    ns = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_")
    if not ns:
        ns = "asset"
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


def reference_character_rigs(character_rigs, film_name):
    """
    References the Shot-Ready (highest _RIG_-tagged) file for each of the
    scene's configured Character/Rigs assets, ADDITIONALLY to whatever the
    copied-in Layout already has (the Proxy) -- both coexist by design, not
    a swap. If an asset hasn't reached Rigging yet, it's skipped (logged)
    rather than referencing a Modeling/Texture-Surface WIP file. Same
    pattern as the (now removed) Animation rig-referencing.
    """
    used_namespaces = set()
    for rig in character_rigs:
        name = rig.get("name") if isinstance(rig, dict) else rig
        if not name:
            continue

        asset_dir = get_asset_production_dir(film_name, "Character/Rigs", name)
        if not asset_dir:
            log(f"ERROR: No folder mapping for Character/Rigs; skipping '{name}'")
            continue

        version, path = find_latest_rig_version(asset_dir, name)
        if not path:
            log(f"WARNING: No Shot-Ready (Rigging) file exists yet for '{name}'; skipping")
            continue

        if not os.path.isfile(path):
            log(f"ERROR: Rig not found on disk: {path}")
            continue

        base = sanitize_namespace(os.path.splitext(os.path.basename(path))[0])
        ns = unique_namespace(base, used_namespaces)

        cmds.file(path, reference=True, namespace=ns, ignoreVersion=True)
        log(f"Referenced Shot-Ready rig: {path} (namespace={ns}, v{version})")


def open_existing_scene(path):
    """Same tolerant-open handling as Assignments.open_existing_scene()."""
    try:
        cmds.file(path, open=True, force=True, ignoreVersion=True)
    except RuntimeError as e:
        log(f"WARNING: Non-fatal errors while opening {path}: {e}")
        cmds.file(rename=path)


def stamp_scene_metadata(film_name, scene_number, shot_number, shot_id, scene_id, display_name):
    cmds.fileInfo("GAA_film", film_name)
    cmds.fileInfo("GAA_scene_number", str(scene_number))
    cmds.fileInfo("GAA_shot_number", str(shot_number))
    cmds.fileInfo("GAA_step", "Blocking")
    cmds.fileInfo("GAA_display_name", display_name)
    if scene_id is not None:
        cmds.fileInfo("GAA_scene_id", str(scene_id))
    if shot_id is not None:
        cmds.fileInfo("GAA_shot_id", str(shot_id))


def stamp_render_dimensions(context):
    """
    Tags the scene with this shot's render resolution, derived server-side
    from the film's aspect ratio preset (Create/Edit Film) -- see
    resolve_render_dimensions() in capstone_routes.py. Lets
    GAAPlayblastTool_V7.py playblast at the right size instead of a
    hardcoded 1920x1080 for every film. No-op if the session context
    predates this (missing render_width/render_height).
    """
    width = context.get("render_width")
    height = context.get("render_height")
    if width and height:
        cmds.fileInfo("GAA_render_width", str(width))
        cmds.fileInfo("GAA_render_height", str(height))


def set_shot_frame_range(frame_count):
    """
    Applies the shot's current frame_count (Edit Layout Config, never
    locked) as a 1-to-frame_count playback range, called on every
    open/create so a coordinator's later revision propagates. No-op if
    frame_count isn't set yet.
    """
    if not frame_count:
        return
    cmds.playbackOptions(
        minTime=1,
        maxTime=frame_count,
        animationStartTime=1,
        animationEndTime=frame_count
    )
    log(f"Frame range set: 1-{frame_count}")


def save_scene(save_path):
    """
    Explicit type="mayaBinary" — see CapstoneLayout.save_scene() for why.
    Path/basename always contain "_BL_" by construction (build_base_name),
    so this can never write to a "_LAY_" filename even if something
    upstream passed a bad path.
    """
    save_dir = os.path.dirname(save_path)
    os.makedirs(save_dir, exist_ok=True)
    cmds.file(rename=save_path)
    cmds.file(save=True, force=True, type="mayaBinary")
    log(f"Scene saved: {save_path}")


# ── Main: shot Blocking ────────────────────────────────────────
def run_shot(login_name=None, shot_id=None):
    """
    Per-shot, created once this shot's own Layout is Approved or CUT (see
    "shot_layout_approved" in the session context -- gate is per-shot, not
    the scene-wide Layout Set flag). First open copies in the shot's own
    approved Layout, then references in the film's configured Character
    Rigs. Subsequent opens just open the latest existing Blocking file,
    same shape as CapstoneLighting.run_shot().
    """
    _init_log()
    log("=" * 50)
    log("CapstoneBlocking.run_shot() started")

    login_name = login_name or getpass.getuser()
    log(f"login_name={login_name} shot_id={shot_id}")

    try:
        context = load_session(login_name)
        if not context:
            return False

        film_name = context["film_name"]
        scene_number = context["scene_number"]
        shot_number = context["shot_number"]
        display_name = context["user"]["display_name"]
        character_rigs = context.get("character_rigs", [])
        frame_count = context.get("frame_count")
        directory = shot_dir(film_name, scene_number, shot_number)
        base_name = build_base_name(film_name, scene_number, shot_number, display_name)

        log(f"Shot: {film_name} / scene {scene_number} / shot {shot_number} | artist: {display_name}")

        existing_version, existing_path = find_latest_version(directory, base_name)

        if existing_path:
            open_existing_scene(existing_path)
            stamp_scene_metadata(film_name, scene_number, shot_number, shot_id,
                                  context["scene_id"], display_name)
            stamp_render_dimensions(context)
            set_shot_frame_range(frame_count)
            log(f"Opened existing Blocking (v{existing_version}): {existing_path}")
            log("CapstoneBlocking.run_shot() completed successfully")
            return True

        if not context.get("shot_layout_approved"):
            log("ERROR: This shot's Layout is not approved (or CUT) yet; Blocking cannot be created")
            cmds.warning("This shot's Layout hasn't been approved yet — Blocking can't start until it is.")
            return False

        _, layout_path = find_latest_layout_any_user(directory, film_name, scene_number, shot_number)
        if not layout_path:
            log(f"ERROR: shot_layout_approved is true but no Layout file found in {directory}")
            cmds.warning("This shot's Layout is approved, but no Layout file could be found on disk for it. Contact your instructor.")
            return False

        # OS-level file copy, not cmds.file(i=True) -- importing a file
        # into an already-open scene flattens its nested references into
        # embedded geometry (confirmed via CapstoneAnimation.py's identical
        # copy-in step: an empty Reference Editor after import, despite
        # pose/position data surviving). Opening a file with references,
        # unlike importing one, preserves them correctly, so copying
        # Layout's file to the Blocking path and opening THAT keeps every
        # reference (Sets/Props/Character Proxy) exactly as Layout had it.
        save_path = os.path.join(directory, f"{base_name}_v1.mb")
        os.makedirs(directory, exist_ok=True)
        shutil.copyfile(layout_path, save_path)
        open_existing_scene(save_path)
        log(f"Copied Layout file to Blocking: {layout_path} -> {save_path}")

        reference_character_rigs(character_rigs, film_name)
        set_shot_frame_range(frame_count)

        stamp_scene_metadata(film_name, scene_number, shot_number, shot_id,
                              context["scene_id"], display_name)
        stamp_render_dimensions(context)

        save_scene(save_path)
        log(f"Created fresh Blocking (copy of Layout + referenced rigs): {save_path}")
        log("CapstoneBlocking.run_shot() completed successfully")
        return True

    except Exception as e:
        log(f"ERROR: Unhandled exception in run_shot(): {e}")
        return False


if __name__ == "__main__":
    import sys
    _login_name = sys.argv[1] if len(sys.argv) > 1 else None
    _shot_id = sys.argv[2] if len(sys.argv) > 2 else None
    run_shot(login_name=_login_name, shot_id=_shot_id)
