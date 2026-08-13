# CapstoneLighting.py
# UC GAA Shot Tracker — silent Maya shot Lighting setup for the capstone
# film pipeline. Invoked by launcher.py (action=shot_lighting) after it has
# written {login_name}_shot_lighting_context.json. Same silent contract as
# the other Capstone*.py modules: no dialogs, no prompts, failures logged
# and returned as False.
#
# Filename convention: {film}_{scene:3d}_{shot:3d}_LGT_{user}_v{n}.mb —
# distinct step code from Layout (_LAY_) and Animation (_ANIM_) by
# construction, so a Lighting session can never save over a Layout or
# Animation file regardless of what's open in Maya.

import os
import re
import json
import getpass
import datetime

import maya.cmds as cmds

# ── Config ────────────────────────────────────────────────────
SESSIONS_PATH = r"C:\Cincy\sessions"
LOG_DIR       = r"C:\Cincy\logs"
FILMS_ROOT    = r"\\GAAAP1PRD01W\Films"

STEP_CODE          = "LGT"
ANIMATION_STEP_CODE = "ANIM"
LGTRIG_STEP_CODE    = "LGTRIG"

# Mirrors CapstoneAnimation.py -- duplicated rather than imported, deploy/
# tools are each self-contained. Used to resolve the Shot-Ready (Rig
# Creation-tagged) file for each of the scene's configured Light Rigs
# assets, the same "look it up on disk by name" pattern Animation uses for
# Character/Rigs, instead of trusting whatever assets.file_path happens to
# hold.
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
    _log_file = os.path.join(LOG_DIR, f"capstone_lighting_{timestamp}.log")


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
    session_file = os.path.join(SESSIONS_PATH, f"{login_name}_shot_lighting_context.json")
    if not os.path.isfile(session_file):
        log(f"ERROR: Shot lighting session context not found: {session_file}")
        return None
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"ERROR: Could not read shot lighting session context {session_file}: {e}")
        return None


# ── Naming / path helpers ─────────────────────────────────────
def pad3(number):
    return str(number).zfill(3)


def shot_dir(film_name, scene_number, shot_number):
    return os.path.join(FILMS_ROOT, film_name, pad3(scene_number), pad3(shot_number))


def build_base_name(film_name, scene_number, shot_number, display_name):
    # STEP_CODE ("LGT") is always embedded here, so this name can never
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


def get_asset_production_dir(film_name, category, asset_name):
    folder = CATEGORY_FOLDER_MAP.get(category)
    if not folder:
        return None
    return os.path.join(ASSET_ROOT, film_name, "Assets", folder, asset_name)


def find_latest_light_rig_version(asset_dir, asset_name):
    """Highest version among files tagged _LGTRIG_ -- the Shot-Ready file, same idea as CapstoneAnimation's find_latest_rig_version()."""
    safe_name = re.escape(asset_name).replace(r"\ ", r"[ _]")
    pattern = re.compile(rf"^{safe_name}_{LGTRIG_STEP_CODE}_.*?_v(\d+)\.(ma|mb)$", re.IGNORECASE)

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
        log(f"WARNING: Could not list {asset_dir} for light rig version scan: {e}")
    return highest, highest_path


def find_latest_animation_any_user(directory, film_name, scene_number, shot_number):
    """Same "pick globally highest version" reasoning as the Layout/Animation copy-in lookups."""
    prefix = f"{film_name}_{pad3(scene_number)}_{pad3(shot_number)}_{ANIMATION_STEP_CODE}_"
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
        log(f"WARNING: Could not list {directory} for animation scan: {e}")
    return highest, highest_path


# ── Maya scene operations ────────────────────────────────────
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


def get_referenced_asset_dirs():
    """Same as CapstoneAnimation.get_referenced_asset_dirs() -- directories of every file currently referenced into the open scene."""
    try:
        paths = cmds.file(query=True, reference=True) or []
    except RuntimeError:
        paths = []
    return {os.path.normcase(os.path.normpath(os.path.dirname(p))) for p in paths}


def _rig_already_present(name, referenced_dirs, asset_dir_norm):
    """Same as CapstoneAnimation._rig_already_present() -- live-reference check plus a namespace-prefix fallback."""
    if asset_dir_norm in referenced_dirs:
        return True
    prefix = (sanitize_namespace(name) + "_LGTRIG_").lower()
    try:
        all_namespaces = cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True) or []
    except RuntimeError:
        all_namespaces = []
    return any(ns.lower().startswith(prefix) for ns in all_namespaces)


def reference_light_rigs(light_rigs, film_name, skip_already_referenced=False):
    """
    References the Shot-Ready (highest _LGTRIG_-tagged) file for each of
    the scene's configured Light Rigs assets, resolved from disk by name --
    same pattern as CapstoneAnimation.reference_character_rigs(), not the
    asset's raw (possibly stale/WIP) assets.file_path. If a light rig
    hasn't reached Rig Creation yet, it's skipped (logged) rather than
    referencing nothing usable.

    skip_already_referenced=True makes this safe to call on every open
    (fresh creation AND reopen): rigs already in the scene are left alone,
    so only newly Shot-Ready assets get added on a later reopen, the same
    backfill behavior Animation has for Character/Rigs.
    """
    used_namespaces = set()
    referenced_dirs = get_referenced_asset_dirs() if skip_already_referenced else set()

    for rig in light_rigs:
        name = rig.get("name") if isinstance(rig, dict) else rig
        if not name:
            continue

        asset_dir = get_asset_production_dir(film_name, "Light Rigs", name)
        if not asset_dir:
            log(f"ERROR: No folder mapping for Light Rigs; skipping '{name}'")
            continue

        if skip_already_referenced and _rig_already_present(
            name, referenced_dirs, os.path.normcase(os.path.normpath(asset_dir))
        ):
            continue

        version, path = find_latest_light_rig_version(asset_dir, name)
        if not path:
            log(f"WARNING: No Shot-Ready (Rig Creation) file exists yet for light rig '{name}'; skipping")
            continue

        if not os.path.isfile(path):
            log(f"ERROR: Light rig not found on disk: {path}")
            continue

        base = sanitize_namespace(os.path.splitext(os.path.basename(path))[0])
        ns = unique_namespace(base, used_namespaces)

        cmds.file(path, reference=True, namespace=ns, ignoreVersion=True)
        log(f"Referenced Shot-Ready light rig: {path} (namespace={ns}, v{version})")


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
    cmds.fileInfo("GAA_step", "Lighting")
    cmds.fileInfo("GAA_display_name", display_name)
    if scene_id is not None:
        cmds.fileInfo("GAA_scene_id", str(scene_id))
    if shot_id is not None:
        cmds.fileInfo("GAA_shot_id", str(shot_id))


def save_scene(save_path):
    """
    Explicit type="mayaBinary" — see CapstoneLayout.save_scene() for why.
    Path/basename always contain "_LGT_" by construction (build_base_name),
    so this can never write to a "_LAY_" filename even if something upstream
    passed a bad path — there is no separate guard needed beyond the naming
    convention itself.
    """
    save_dir = os.path.dirname(save_path)
    os.makedirs(save_dir, exist_ok=True)
    cmds.file(rename=save_path)
    cmds.file(save=True, force=True, type="mayaBinary")
    log(f"Scene saved: {save_path}")


# ── Main: shot Lighting ───────────────────────────────────────
def run_shot(login_name=None, shot_id=None):
    """
    Per-shot, created once Animation is approved. First open copies in the
    approved Animation (the animated shot content to light against), then
    references in the film's Light Rigs assets. Subsequent opens just open
    the latest existing Lighting file, same shape as
    CapstoneAnimation.run_shot().
    """
    _init_log()
    log("=" * 50)
    log("CapstoneLighting.run_shot() started")

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
        directory = shot_dir(film_name, scene_number, shot_number)
        base_name = build_base_name(film_name, scene_number, shot_number, display_name)

        log(f"Shot: {film_name} / scene {scene_number} / shot {shot_number} | artist: {display_name}")

        existing_version, existing_path = find_latest_version(directory, base_name)

        if existing_path:
            open_existing_scene(existing_path)
            stamp_scene_metadata(film_name, scene_number, shot_number, shot_id,
                                  context["scene_id"], display_name)
            reference_light_rigs(context.get("light_rigs", []), film_name, skip_already_referenced=True)
            log(f"Opened existing Lighting (v{existing_version}): {existing_path}")
            log("CapstoneLighting.run_shot() completed successfully")
            return True

        if not context.get("animation_locked"):
            log("ERROR: Animation is not approved yet; Lighting cannot be created")
            cmds.warning("This shot's Animation hasn't been approved yet — Lighting can't start until it is.")
            return False

        _, animation_path = find_latest_animation_any_user(directory, film_name, scene_number, shot_number)
        if not animation_path:
            log(f"ERROR: animation_locked is true but no Animation file found in {directory}")
            cmds.warning("Animation is marked approved, but no Animation file could be found on disk. Contact your instructor.")
            return False

        cmds.file(new=True, force=True)
        cmds.file(animation_path, i=True, ignoreVersion=True)
        log(f"Copied in Animation: {animation_path}")

        reference_light_rigs(context.get("light_rigs", []), film_name, skip_already_referenced=True)

        stamp_scene_metadata(film_name, scene_number, shot_number, shot_id,
                              context["scene_id"], display_name)

        save_path = os.path.join(directory, f"{base_name}_v1.mb")
        save_scene(save_path)
        log(f"Created fresh Lighting (copy-in from Animation + referenced light rigs): {save_path}")
        log("CapstoneLighting.run_shot() completed successfully")
        return True

    except Exception as e:
        log(f"ERROR: Unhandled exception in run_shot(): {e}")
        return False


if __name__ == "__main__":
    import sys
    _login_name = sys.argv[1] if len(sys.argv) > 1 else None
    _shot_id = sys.argv[2] if len(sys.argv) > 2 else None
    run_shot(login_name=_login_name, shot_id=_shot_id)
