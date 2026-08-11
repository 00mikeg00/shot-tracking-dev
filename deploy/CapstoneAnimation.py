# CapstoneAnimation.py
# UC GAA Shot Tracker — silent Maya shot Animation setup for the capstone
# film pipeline. Invoked by launcher.py (action=shot_animation) after it has
# written {login_name}_shot_animation_context.json. Same silent contract as
# Assignments.run() and CapstoneLayout.run_shot(): no dialogs, no prompts,
# failures logged and returned as False.
#
# Animation now has its own Blocking/Blocking Plus/Polish sub-steps (BL/BP/P
# short codes), same shape as Assignments.py's Blocking/Blocking Plus/Polish
# for individual assignments -- resolve_current_step()/find_carry_forward_
# source()/create_or_continue_step() below are ported from there, just
# scoped to shot_id instead of individual_assignment_id, and hitting the
# /shot-animation-substep/* endpoints instead of /steps/*. Blocking itself
# can only be locked by a coordinator (see capstone_routes.shot_blocking_
# approve) -- Blocking Plus/Polish are self-locked by the artist via GAA
# Save, same as assignments.
#
# Filename convention: {film}_{scene:3d}_{shot:3d}_ANIM_{user}_{BL|BP|P}_V###.mb
# -- keeps the existing ANIM tag (GAA_step stays "Animation" in fileInfo, so
# GAAPlayblastTool_V7.py's FILM_STEP_CODES/review_routes.py's glob patterns,
# which only know LAY/ANIM/LGT, keep working unchanged across all three
# sub-steps) with the sub-step code and a zero-padded version appended,
# mirroring Assignments.py's {base}_{STEP}_V###.ma shape.

import os
import re
import json
import getpass
import datetime

import requests
import maya.cmds as cmds

# ── Config ────────────────────────────────────────────────────
SESSIONS_PATH = r"C:\Cincy\sessions"
LOG_DIR       = r"C:\Cincy\logs"
FILMS_ROOT    = r"\\GAAAP1PRD01W\Films"
SHOT_TRACKER_URL = os.environ.get("SHOT_TRACKER_URL", "http://10.23.20.210:8000")

STEP_CODE        = "ANIM"
LAYOUT_STEP_CODE = "LAY"

# Steps that get their own versioned file within Animation. Matches
# Assignments.py's FILE_VERSIONED_STEP_CODES exactly -- same three-pass
# shape (first pass reviewed by a coordinator, the rest self-managed).
FILE_VERSIONED_STEP_CODES = {"BL", "BP", "P"}

# Mirrors Assets.py/CapstoneLayout.py -- duplicated rather than imported,
# deploy/ tools are each self-contained. Used to reference the Shot-Ready
# rig for each of the scene's configured Character/Rigs assets, alongside
# whatever the copied-in Layout already brought in (the Proxy) -- see
# reference_character_rigs().
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
    _log_file = os.path.join(LOG_DIR, f"capstone_animation_{timestamp}.log")


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
    session_file = os.path.join(SESSIONS_PATH, f"{login_name}_shot_animation_context.json")
    if not os.path.isfile(session_file):
        log(f"ERROR: Shot animation session context not found: {session_file}")
        return None
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"ERROR: Could not read shot animation session context {session_file}: {e}")
        return None


def fetch_shot_animation_context(shot_id, login_name):
    """
    Same call launcher.py's get_shot_animation_context() makes, duplicated
    here (deploy/ tools stay self-contained) so GAASave.py can re-resolve a
    capstone shot scene's context live from the currently open scene's
    GAA_shot_id tag, rather than trusting the last-written session file --
    which belongs to whichever shot was most recently opened via the
    launcher, not necessarily the one open right now.
    """
    try:
        r = requests.get(
            f"{SHOT_TRACKER_URL}/classes/api/launcher/capstone/shot-animation/context",
            params={"shot_id": shot_id, "login_name": login_name},
            timeout=10
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"ERROR: Could not fetch shot animation context for shot_id={shot_id}: {e}")
        return None


def resolve_scene_context(login_name=None):
    """
    Returns (context, login_name) for the capstone shot the CURRENTLY OPEN
    scene belongs to (read from its GAA_shot_id fileInfo tag, stamped by
    stamp_scene_metadata() on every scene this module creates/opens), or
    (None, None) if the open scene isn't a capstone Animation scene at all
    -- that's how GAASave.py tells a capstone shot scene apart from a
    regular assignment scene (Assignments.resolve_scene_context() instead,
    via GAA_individual_assignment_id).
    """
    login_name = login_name or getpass.getuser()

    tagged_shot_id = cmds.fileInfo("GAA_shot_id", q=True)
    tagged_shot_id = tagged_shot_id[0] if tagged_shot_id else None
    if not tagged_shot_id:
        return None, None

    context = fetch_shot_animation_context(int(tagged_shot_id), login_name)
    if not context:
        return None, None

    return context, login_name


# ── Step / lock API (Blocking/Blocking Plus/Polish) ────────────
def fetch_steps_status(shot_id):
    """
    Live lock/step state for this shot's Blocking/Blocking Plus/Polish.
    Returns None (not []) on any failure to fetch, so callers can tell
    "server unreachable" apart from "shot genuinely has no sub-steps yet
    (migration not run for this film)".
    """
    try:
        r = requests.get(
            f"{SHOT_TRACKER_URL}/classes/api/launcher/capstone/shot-animation-substep/status",
            params={"shot_id": shot_id},
            timeout=10
        )
        r.raise_for_status()
        return r.json().get("steps", [])
    except Exception as e:
        log(f"ERROR: Could not fetch Animation sub-step status: {e}")
        return None


def resolve_current_step(steps):
    """
    Same logic as Assignments.resolve_current_step(): the lowest-order_num
    unlocked file-versioned step, or the last one if every one of them is
    locked (nothing further to advance into -- Polish locked means Animation
    is submitted and waiting on the coordinator's Animation approval).
    Returns None only if steps is empty.
    """
    if not steps:
        return None

    file_steps = [s for s in steps if s.get("short_code") in FILE_VERSIONED_STEP_CODES]
    if not file_steps:
        return None

    unlocked = [s for s in file_steps if not s["locked"]]
    if unlocked:
        return min(unlocked, key=lambda s: s["order_num"])
    return max(file_steps, key=lambda s: s["order_num"])


def find_next_step(steps, current_step):
    """The file-versioned sub-step immediately after current_step by order_num, or None if it's Polish."""
    candidates = sorted(
        (s for s in steps
         if s.get("short_code") in FILE_VERSIONED_STEP_CODES
         and s["order_num"] > current_step["order_num"]),
        key=lambda s: s["order_num"]
    )
    return candidates[0] if candidates else None


def lock_step(shot_id, step_name, login_name):
    """
    Self-lock for Blocking Plus/Polish (GAA Save's 'Lock this step'
    checkbox). Blocking itself will be rejected server-side (403) --
    it can only be locked via the coordinator's Approve Blocking button.
    """
    try:
        r = requests.post(
            f"{SHOT_TRACKER_URL}/classes/api/launcher/capstone/shot-animation-substep/lock",
            json={"shot_id": shot_id, "step_name": step_name, "login_name": login_name},
            timeout=10
        )
        return r.status_code == 200, (r.json() if r.content else {})
    except Exception as e:
        log(f"ERROR: Could not lock step: {e}")
        return False, {"error": str(e)}


def unlock_step(shot_id, step_name, login_name):
    try:
        r = requests.post(
            f"{SHOT_TRACKER_URL}/classes/api/launcher/capstone/shot-animation-substep/unlock",
            json={"shot_id": shot_id, "step_name": step_name, "login_name": login_name},
            timeout=10
        )
        return r.status_code == 200, (r.json() if r.content else {})
    except Exception as e:
        log(f"ERROR: Could not unlock step: {e}")
        return False, {"error": str(e)}


# ── Naming / path helpers ─────────────────────────────────────
def pad3(number):
    return str(number).zfill(3)


def shot_dir(film_name, scene_number, shot_number):
    return os.path.join(FILMS_ROOT, film_name, pad3(scene_number), pad3(shot_number))


def build_base_name(film_name, scene_number, shot_number, display_name):
    return f"{film_name}_{pad3(scene_number)}_{pad3(shot_number)}_{STEP_CODE}_{display_name}"


def find_latest_step_scene(directory, base_name, step_code):
    """
    Highest {base_name}_{step_code}_V###.mb in directory -- one continuous
    version family per sub-step, same idea as Assignments.
    find_latest_step_scene(). A pre-sub-step file like {base_name}_v3.mb
    (the old flat convention) simply won't match, so it's correctly
    invisible here.
    """
    pattern = re.compile(
        rf"^{re.escape(base_name)}_{re.escape(step_code)}_V(\d+)\.mb$",
        re.IGNORECASE
    )
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
        log(f"WARNING: Could not list {directory} for step version scan: {e}")
    return highest, highest_path


def find_carry_forward_source(steps, current_step, directory, base_name):
    """
    For a current step with no file of its own yet, finds the highest-order
    prior file-versioned step that does have an existing file, so Blocking
    Plus/Polish continue the previous pass instead of starting blank.
    Returns (step, version, path), or (None, None, None) if current_step is
    Blocking itself (nothing prior) or its file genuinely doesn't exist yet.
    """
    candidates = sorted(
        (s for s in steps
         if s.get("short_code") in FILE_VERSIONED_STEP_CODES
         and s["order_num"] < current_step["order_num"]),
        key=lambda s: s["order_num"],
        reverse=True
    )
    for s in candidates:
        version, path = find_latest_step_scene(directory, base_name, s["short_code"])
        if path:
            return s, version, path
    return None, None, None


def find_latest_layout_any_user(directory, film_name, scene_number, shot_number):
    """
    Highest {film}_{scene}_{shot}_LAY_*_v{N}.mb in the shot folder, for
    Blocking's first-open copy-in. Unlike scene Layout (one shared file),
    shot Layout could in principle have been saved by more than one login
    across a semester (e.g. a redo) — same "pick globally highest version,
    not scoped to a specific user" reasoning as
    CapstoneLayout.find_latest_version_any_user().
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


def get_referenced_asset_dirs():
    """
    Directories (normalized) of every file currently referenced into the
    open scene. Used to tell whether a given Character/Rigs asset already
    has a reference in the scene, regardless of which version was
    referenced -- so re-running reference_character_rigs() on an already
    set-up scene doesn't create duplicate references.
    """
    try:
        paths = cmds.file(query=True, reference=True) or []
    except RuntimeError:
        paths = []
    return {os.path.normcase(os.path.normpath(os.path.dirname(p))) for p in paths}


def reference_character_rigs(character_rigs, film_name, skip_already_referenced=False):
    """
    References the Shot-Ready (highest _RIG_-tagged) file for each of the
    scene's configured Character/Rigs assets, ADDITIONALLY to whatever the
    copied-in Layout already has (the Proxy) -- both coexist in the
    Animation scene by design, not a swap. If an asset hasn't reached
    Rigging yet, it's skipped (logged) rather than referencing a
    Modeling/Texture-Surface WIP file.

    skip_already_referenced=True makes this safe to call on a scene that's
    already been set up (e.g. every re-open of an existing Blocking/
    Blocking Plus/Polish file): assets whose asset folder already has a
    reference in the scene are left alone, so only newly Shot-Ready assets
    get added.
    """
    used_namespaces = set()
    referenced_dirs = get_referenced_asset_dirs() if skip_already_referenced else set()

    for rig in character_rigs:
        name = rig.get("name") if isinstance(rig, dict) else rig
        if not name:
            continue

        asset_dir = get_asset_production_dir(film_name, "Character/Rigs", name)
        if not asset_dir:
            log(f"ERROR: No folder mapping for Character/Rigs; skipping '{name}'")
            continue

        if skip_already_referenced and os.path.normcase(os.path.normpath(asset_dir)) in referenced_dirs:
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


# ── Maya scene operations ────────────────────────────────────
def open_existing_scene(path):
    """Same tolerant-open handling as Assignments.open_existing_scene()."""
    try:
        cmds.file(path, open=True, force=True, ignoreVersion=True)
    except RuntimeError as e:
        log(f"WARNING: Non-fatal errors while opening {path}: {e}")
        cmds.file(rename=path)


def stamp_scene_metadata(film_name, scene_number, shot_number, shot_id, scene_id, display_name):
    """
    GAA_step stays "Animation" (not the Blocking/Blocking Plus/Polish
    sub-step name) regardless of which sub-step this scene is -- see
    module docstring: GAAPlayblastTool_V7.py's FILM_STEP_CODES only knows
    LAY/ANIM/LGT, and this keeps that working unchanged across all three
    sub-steps.
    """
    cmds.fileInfo("GAA_film", film_name)
    cmds.fileInfo("GAA_scene_number", str(scene_number))
    cmds.fileInfo("GAA_shot_number", str(shot_number))
    cmds.fileInfo("GAA_step", "Animation")
    cmds.fileInfo("GAA_display_name", display_name)
    if scene_id is not None:
        cmds.fileInfo("GAA_scene_id", str(scene_id))
    if shot_id is not None:
        cmds.fileInfo("GAA_shot_id", str(shot_id))


def save_scene(save_path):
    """Explicit type="mayaBinary" — see CapstoneLayout.save_scene() for why."""
    save_dir = os.path.dirname(save_path)
    os.makedirs(save_dir, exist_ok=True)
    cmds.file(rename=save_path)
    cmds.file(save=True, force=True, type="mayaBinary")
    log(f"Scene saved: {save_path}")


def create_or_continue_step(steps, current_step, directory, base_name, film_name, scene_number,
                             shot_number, shot_id, scene_id, display_name, character_rigs,
                             scene_layout_done):
    """
    Creates the first file for current_step (must be file-versioned).
    Continues from the highest-order prior file-versioned step's latest
    file if one exists (Blocking Plus/Polish refine the previous pass);
    otherwise this must be Blocking itself with no file yet -- builds the
    scene fresh from the approved Layout, exactly like the old single
    fresh-create branch.

    Returns (True, save_path) on success, or (False, None) on failure
    (already logged).
    """
    step_code = current_step["short_code"]
    prev_step, prev_version, prev_path = find_carry_forward_source(steps, current_step, directory, base_name)

    if prev_path:
        open_existing_scene(prev_path)
        save_path = os.path.join(directory, f"{base_name}_{step_code}_V001.mb")
        stamp_scene_metadata(film_name, scene_number, shot_number, shot_id, scene_id, display_name)
        # New Shot-Ready rigs that appeared since prev_step's file was
        # created still get picked up here, same reasoning as the
        # existing-scene backfill in run_shot().
        reference_character_rigs(character_rigs, film_name, skip_already_referenced=True)
        save_scene(save_path)
        log(f"Carried into {current_step['name']} from {prev_step['name']} V{prev_version:03d}: {save_path}")
        return True, save_path

    # No prior sub-step file -- this is Blocking's first-ever creation.
    if not scene_layout_done:
        log("ERROR: Scene Layout is not marked done yet; Blocking cannot be created")
        cmds.warning("This shot's scene Layout hasn't been marked done yet — Animation can't start until it is.")
        return False, None

    _, layout_path = find_latest_layout_any_user(directory, film_name, scene_number, shot_number)
    if not layout_path:
        log(f"ERROR: scene_layout_done is true but no Layout file found in {directory}")
        cmds.warning("Scene Layout is marked done, but no Layout file could be found on disk for this shot. Contact your instructor.")
        return False, None

    cmds.file(new=True, force=True)
    cmds.file(layout_path, i=True, ignoreVersion=True)
    log(f"Copied in Layout: {layout_path}")

    # Additionally reference the Shot-Ready rig for each Character/Rigs
    # asset configured on this scene, alongside the Proxy the copy-in just
    # brought in -- both coexist, this is not a swap (the Proxy keeps
    # whatever animation gets keyed on it; the real rig is here too, per
    # the confirmed design).
    reference_character_rigs(character_rigs, film_name)

    stamp_scene_metadata(film_name, scene_number, shot_number, shot_id, scene_id, display_name)

    save_path = os.path.join(directory, f"{base_name}_{step_code}_V001.mb")
    save_scene(save_path)
    log(f"Created fresh {current_step['name']} (copy-in from Layout): {save_path}")
    return True, save_path


def open_or_create_step(steps, step, directory, base_name, film_name, scene_number, shot_number,
                         shot_id, scene_id, display_name, character_rigs, scene_layout_done):
    """
    Opens step's latest file if one already exists, otherwise creates it.
    Shared by run_shot() and GAASave.py (advancing into the next sub-step
    right after a lock), same split as Assignments.open_or_create_step().

    Returns (success, action, path) where action is "opened" or "created"
    (None on failure, already logged).
    """
    version, path = find_latest_step_scene(directory, base_name, step["short_code"])

    if path:
        open_existing_scene(path)
        stamp_scene_metadata(film_name, scene_number, shot_number, shot_id, scene_id, display_name)
        reference_character_rigs(character_rigs, film_name, skip_already_referenced=True)
        return True, "opened", path

    success, save_path = create_or_continue_step(
        steps, step, directory, base_name, film_name, scene_number, shot_number,
        shot_id, scene_id, display_name, character_rigs, scene_layout_done
    )
    return success, ("created" if success else None), save_path


# ── Main: shot Animation ──────────────────────────────────────
def run_shot(login_name=None, shot_id=None):
    _init_log()
    log("=" * 50)
    log("CapstoneAnimation.run_shot() started")

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
        scene_layout_done = bool(context.get("scene_layout_done"))
        directory = shot_dir(film_name, scene_number, shot_number)
        base_name = build_base_name(film_name, scene_number, shot_number, display_name)

        log(f"Shot: {film_name} / scene {scene_number} / shot {shot_number} | artist: {display_name}")

        steps = fetch_steps_status(shot_id)
        if steps is None:
            log("ERROR: Could not fetch Blocking/Blocking Plus/Polish status; aborting")
            cmds.warning("Could not reach Shot Tracker to check Animation's step status. Try again.")
            return False

        current_step = resolve_current_step(steps)
        if current_step is None:
            log("ERROR: This film's workflow has no Blocking/Blocking Plus/Polish steps configured")
            cmds.warning("This film's workflow doesn't have Blocking/Blocking Plus/Polish set up yet. Contact your instructor.")
            return False

        success, action, path = open_or_create_step(
            steps, current_step, directory, base_name, film_name, scene_number, shot_number,
            shot_id, context["scene_id"], display_name, character_rigs, scene_layout_done
        )
        if not success:
            return False

        verb = "Opened existing" if action == "opened" else "Created"
        log(f"{verb} {current_step['name']}: {path}")
        log("CapstoneAnimation.run_shot() completed successfully")
        return True

    except Exception as e:
        log(f"ERROR: Unhandled exception in run_shot(): {e}")
        return False


if __name__ == "__main__":
    import sys
    _login_name = sys.argv[1] if len(sys.argv) > 1 else None
    _shot_id = sys.argv[2] if len(sys.argv) > 2 else None
    run_shot(login_name=_login_name, shot_id=_shot_id)
