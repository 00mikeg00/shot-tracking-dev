# Assets.py
# UC GAA Shot Tracker — silent Maya asset production (Modeling / Texture-
# Surface / Rigging) setup. Invoked by launcher.py (action=asset) after it
# has written {login_name}_asset_context.json. Same silent contract as
# Assignments.run(): no dialogs, no prompts, failures logged and returned
# as False.
#
# Versioning is CONTINUOUS across Modeling/Texture-Surface/Rigging -- one
# version counter for the asset's whole life, NOT reset per step like
# Assignments.py's Blocking/Blocking Plus/Polish. This matches how asset
# files already exist on disk (e.g. "Dally No. 1_Charlotte Bodie_v004.mb",
# no step in the name at all) and keeps app/utils/utils.py's
# find_matching_asset_file() / the "Sync from Disk" action correct --
# those pick whichever file has the highest version number in the asset's
# folder with no awareness of steps, so a reset-per-step scheme would make
# them intermittently point at a stale earlier-step file. See
# find_latest_asset_version() below, which deliberately mirrors that same
# regex shape so both stay in agreement about what "the current file" is.
#
# Locking still applies per step (step_locks, entity_type='asset_step') --
# only the on-disk numbering is flat, not the approval gating.
#
# Opening on a step BOUNDARY (the previous file-versioned step just got
# locked, e.g. Modeling -> Texture-Surface) copies the file forward as a
# new version tagged with the new step, rather than silently reopening the
# prior step's file under its old name -- see extract_step_code() / the
# transition branch in run(). Opening again within the SAME step (no
# transition) just reopens the latest file as-is, same as Assignments.py.

import os
import re
import json
import getpass
import datetime
import requests

import maya.cmds as cmds

# ── Config ────────────────────────────────────────────────────
SESSIONS_PATH     = r"C:\Cincy\sessions"
LOG_DIR           = r"C:\Cincy\logs"
ASSET_ROOT        = r"\\GAAAP1PRD01W\Films"
SHOT_TRACKER_URL  = os.environ.get("SHOT_TRACKER_URL", "http://10.23.20.210:8000")

# Mirrors app/utils/utils.py:CATEGORY_FOLDER_MAP -- single source of truth
# duplicated here since Maya-side deploy/ tools don't import Flask app
# code (same split as every other deploy/*.py module).
CATEGORY_FOLDER_MAP = {
    "Sets": "Sets",
    "Character/Rigs": "Rigs",
    "Rigs": "Rigs",
    "Props - 3D": "Props_-_3D",
    "Props - 2D": "Props_-_2D",
    "Light Rigs": "LightRigs",
    "BGs": "BGs",
}

# Steps that actually get their own Maya scene file, matching the
# step_codes rows added by migrate_add_asset_step_codes.py. Design and
# Shot Ready aren't file-producing steps (concept art / a final gate), and
# FB-*/Grade-* pseudo-steps are excluded server-side already. A category
# whose steps don't include any of these (e.g. Props - 2D, or Light Rigs'
# "Rig Creation" step which has no code yet) simply has nothing to open --
# see run()'s current_step is None branch.
FILE_VERSIONED_STEP_CODES = {"MOD", "TEX", "RIG"}

_log_file = None


# ── Logging ───────────────────────────────────────────────────
def _init_log():
    global _log_file
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_file = os.path.join(LOG_DIR, f"assets_{timestamp}.log")


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
    session_file = os.path.join(SESSIONS_PATH, f"{login_name}_asset_context.json")
    if not os.path.isfile(session_file):
        log(f"ERROR: Asset session context not found: {session_file}")
        return None
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"ERROR: Could not read asset session context {session_file}: {e}")
        return None


# ── Step / lock API ───────────────────────────────────────────
def fetch_asset_steps_status(asset_id):
    """Live lock/step state from Shot Tracker for one asset. Same contract as Assignments.fetch_steps_status()."""
    try:
        r = requests.get(
            f"{SHOT_TRACKER_URL}/classes/api/launcher/asset-steps/status",
            params={"asset_id": asset_id},
            timeout=10
        )
        r.raise_for_status()
        return r.json().get("steps", [])
    except Exception as e:
        log(f"ERROR: Could not fetch asset step status: {e}")
        return None


def resolve_current_step(steps):
    """
    Identical algorithm to Assignments.resolve_current_step(): among the
    file-versioned steps (Modeling/Texture-Surface/Rigging here instead of
    Blocking/Blocking Plus/Polish), the lowest order_num one that's
    unlocked, or the last one if every one of them is locked. Returns None
    if this asset's category has no file-versioned steps at all (e.g.
    Props - 2D) -- that's an expected, not an error, case; see run().
    """
    if not steps:
        return None

    file_steps = [s for s in steps if s.get("short_code") in FILE_VERSIONED_STEP_CODES]
    if file_steps:
        unlocked = [s for s in file_steps if not s["locked"]]
        if unlocked:
            return min(unlocked, key=lambda s: s["order_num"])
        return max(file_steps, key=lambda s: s["order_num"])

    return None


# ── Naming / path helpers ─────────────────────────────────────
def get_asset_dir(film_name, category, asset_name):
    folder = CATEGORY_FOLDER_MAP.get(category)
    if not folder:
        return None
    return os.path.join(ASSET_ROOT, film_name, "Assets", folder, asset_name)


_STEP_CODE_IN_FILENAME = re.compile(r"_(MOD|TEX|RIG)_", re.IGNORECASE)


def extract_step_code(filename):
    """
    Pulls the step short code back out of a filename this module saved
    (always "{asset_name}_{STEP}_{artist}_v{n}.mb" -- see save path
    construction in run()). Returns None for a file that predates this
    convention (e.g. an old "AssetName_Artist_v004.mb" with no step
    token) -- callers treat that as "can't tell, so don't force a
    transition."
    """
    match = _STEP_CODE_IN_FILENAME.search(filename)
    return match.group(1).upper() if match else None


def find_latest_asset_version(asset_dir, asset_name):
    """
    Mirrors app/utils/utils.py:find_matching_asset_file()'s regex (name,
    then anything, then _v###, then .ma or .mb) so both sides agree on
    what "the current file" is regardless of which step produced it --
    EXCEPT Proxy files, which are deliberately excluded here (and must be
    in find_matching_asset_file() too). Proxy is its own independent
    lineage, never part of the Modeling/Texture-Surface/Rigging continuous
    count -- without this exclusion, a brand-new asset with only a Proxy
    file would make this function report the proxy as "the" MOD/TEX/RIG
    file, and the run() flow below would silently open (and risk
    overwriting) it directly under a production step instead of
    duplicating it forward. See duplicate_proxy_into_step().
    """
    safe_name = re.escape(asset_name).replace(r"\ ", r"[ _]")
    pattern = re.compile(rf"^{safe_name}.*?_v(\d+)\.(ma|mb)$", re.IGNORECASE)

    highest = 0
    highest_path = None
    try:
        for entry in os.listdir(asset_dir):
            if "_PROXY_" in entry.upper():
                continue
            match = pattern.match(entry)
            if match:
                version = int(match.group(1))
                if version > highest:
                    highest = version
                    highest_path = os.path.join(asset_dir, entry)
    except OSError as e:
        log(f"WARNING: Could not list {asset_dir} for version scan: {e}")
    return highest, highest_path


# Maps the human step names the dashboard/session context use to the short
# codes embedded in saved filenames (see save path construction in run()).
# "Proxy" is Character/Rigs-only and, unlike MOD/TEX/RIG, has no lock/FB
# gate at all (see migrate_add_proxy_step.py) -- every asset OPEN for it
# goes through the same requested_step_name branch the coordinator
# override-open uses, just always, not as an exception to normal gating.
STEP_NAME_TO_CODE = {
    "Proxy": "PROXY",
    "Modeling": "MOD",
    "Texture/Surface": "TEX",
    "Rigging": "RIG",
}


def find_latest_version_for_step(asset_dir, asset_name, step_code):
    """
    Highest version among files SPECIFICALLY tagged with step_code (e.g.
    the last Modeling-tagged save, even if Texture-Surface/Rigging have
    since produced higher-numbered files) -- used only by the coordinator
    override-open path (run()'s requested_step_name branch), for going
    back to fix something in an already-approved step. Ordinary opens use
    find_latest_asset_version() instead, which doesn't care which step
    produced the file.
    """
    safe_name = re.escape(asset_name).replace(r"\ ", r"[ _]")
    pattern = re.compile(rf"^{safe_name}_{step_code}_.*?_v(\d+)\.(ma|mb)$", re.IGNORECASE)

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
        log(f"WARNING: Could not list {asset_dir} for step version scan: {e}")
    return highest, highest_path


# ── Maya scene operations ────────────────────────────────────
def open_existing_scene(path):
    """Same tolerant-open handling as Assignments.open_existing_scene()."""
    try:
        cmds.file(path, open=True, force=True, ignoreVersion=True)
    except RuntimeError as e:
        log(f"WARNING: Non-fatal errors while opening {path}: {e}")
        cmds.file(rename=path)


def stamp_asset_metadata(film_name, category, asset_name, current_step_name, display_name, asset_id):
    """
    Tags the scene with fileInfo, same idea as Assignments.stamp_scene_metadata() --
    lets GAAPlayblastTool_V7.py or future tools identify this scene without
    parsing the filename.
    """
    cmds.fileInfo("GAA_film", film_name)
    cmds.fileInfo("GAA_asset_category", category)
    cmds.fileInfo("GAA_asset_name", asset_name)
    cmds.fileInfo("GAA_asset_id", str(asset_id))
    cmds.fileInfo("GAA_step", current_step_name)
    cmds.fileInfo("GAA_display_name", display_name)


def save_scene(save_path):
    """Explicit type="mayaBinary" -- see CapstoneLayout.save_scene() for why."""
    save_dir = os.path.dirname(save_path)
    os.makedirs(save_dir, exist_ok=True)
    cmds.file(rename=save_path)
    cmds.file(save=True, force=True, type="mayaBinary")
    log(f"Scene saved: {save_path}")


# ── Main ──────────────────────────────────────────────────────
def run(login_name=None, asset_id=None):
    _init_log()
    log("=" * 50)
    log("Assets.py started")

    login_name = login_name or getpass.getuser()
    log(f"login_name={login_name} asset_id={asset_id}")

    try:
        context = load_session_context(login_name)
        if not context:
            return False

        film_name = context["film_name"]
        category = context["category"]
        asset_name = context["asset_name"]
        display_name = context["user"]["display_name"]

        log(f"Asset: {asset_name} ({category}) | film: {film_name} | artist: {display_name}")

        asset_dir = get_asset_dir(film_name, category, asset_name)
        if not asset_dir:
            log(f"ERROR: Category '{category}' has no on-disk folder mapping (CATEGORY_FOLDER_MAP); cannot resolve asset directory")
            cmds.warning(f"'{category}' assets aren't mapped to a folder convention yet — contact your instructor.")
            return False

        # Explicit step request -- two callers hit this:
        #   1. Proxy (Character/Rigs only): has no lock/FB gate at all (see
        #      migrate_add_proxy_step.py), so EVERY Proxy open goes through
        #      here, always -- it's not an exception to normal gating, there
        #      is no normal gating for it. Its version counter is fully
        #      independent of MOD/TEX/RIG's (find_latest_version_for_step
        #      scoped to "PROXY" never sees their files or vice versa).
        #   2. Coordinator override-open (Assets page "Open" picker) for
        #      Modeling/Texture-Surface/Rigging: bypasses lock/
        #      resolve_current_step() entirely, to get back into an
        #      already-approved step to fix something after the fact.
        # Either way: open the highest version tagged with THAT step's
        # code, not the asset's global highest version -- those can differ
        # once later steps have produced newer files.
        requested_step_name = context.get("requested_step_name")
        if requested_step_name:
            step_code = STEP_NAME_TO_CODE.get(requested_step_name)
            if not step_code:
                log(f"ERROR: '{requested_step_name}' is not a valid step to open (expected Proxy/Modeling/Texture/Surface/Rigging)")
                cmds.warning(f"'{requested_step_name}' isn't a step this tool knows how to open.")
                return False

            version, path = find_latest_version_for_step(asset_dir, asset_name, step_code)

            if path:
                open_existing_scene(path)
                stamp_asset_metadata(film_name, category, asset_name, requested_step_name, display_name, asset_id)
                log(f"OPEN ({requested_step_name}): v{version}: {path}")
                log("Assets.py completed successfully")
                return True

            # Nothing tagged with this step yet. Proxy is its own lineage,
            # so it always starts at v1. MOD/TEX/RIG share one continuous
            # lineage -- this branch is only reached for them via an
            # unusual coordinator override on an asset that skipped a step,
            # and even then the new file should continue the asset's
            # overall version count, not restart it.
            if step_code == "PROXY":
                next_version = 1
            else:
                global_highest, _ = find_latest_asset_version(asset_dir, asset_name)
                next_version = global_highest + 1

            cmds.file(new=True, force=True)
            stamp_asset_metadata(film_name, category, asset_name, requested_step_name, display_name, asset_id)
            save_path = os.path.join(asset_dir, f"{asset_name}_{step_code}_{display_name}_v{next_version}.mb")
            save_scene(save_path)
            log(f"Created fresh {requested_step_name} file: {save_path}")
            log("Assets.py completed successfully")
            return True

        steps = fetch_asset_steps_status(asset_id)
        current_step = resolve_current_step(steps) if steps is not None else None

        if current_step is None:
            if steps is None:
                log("ERROR: Could not fetch asset step status; nothing to open")
            else:
                log(f"ERROR: '{category}' has no Modeling/Texture-Surface/Rigging step to open in Maya (steps: {[s.get('name') for s in steps]})")
            cmds.warning("This asset's category has no Modeling/Texture/Rigging step to open in Maya.")
            return False

        existing_version, existing_path = find_latest_asset_version(asset_dir, asset_name)

        if existing_path:
            existing_step_code = extract_step_code(os.path.basename(existing_path))
            current_step_code = current_step.get("short_code")

            if existing_step_code and current_step_code and existing_step_code != current_step_code:
                # Step transition (e.g. Modeling just got locked, Texture-
                # Surface is now current): copy the file forward as a NEW
                # version tagged with the new step, rather than silently
                # continuing to save over the prior step's filename. Version
                # number still only counts up (continuous versioning, see
                # module docstring) -- it does not reset to 1 here.
                open_existing_scene(existing_path)
                new_version = existing_version + 1
                new_path = os.path.join(asset_dir, f"{asset_name}_{current_step_code}_{display_name}_v{new_version}.mb")
                stamp_asset_metadata(film_name, category, asset_name, current_step["name"], display_name, asset_id)
                save_scene(new_path)
                log(f"Step transition {existing_step_code} -> {current_step_code}: copied v{existing_version} -> v{new_version}: {new_path}")
                log("Assets.py completed successfully")
                return True

            open_existing_scene(existing_path)
            stamp_asset_metadata(film_name, category, asset_name, current_step["name"], display_name, asset_id)
            log(f"Opened existing asset file (v{existing_version}, current step: {current_step['name']}): {existing_path}")
            log("Assets.py completed successfully")
            return True

        # No MOD/TEX/RIG file exists yet at all for this asset. If this is
        # Modeling specifically and a Proxy exists, duplicate the Proxy
        # forward into Modeling's own v1 -- the proxy was built to become
        # the starting point for the real model, not thrown away. Never
        # opens/saves over the proxy file itself; this always writes a
        # brand-new MOD-tagged file. Any other case (no proxy, or this
        # isn't Modeling) starts genuinely blank, as before.
        step_code = current_step.get("short_code") or "WIP"
        proxy_version, proxy_path = (None, None)
        if step_code == "MOD":
            proxy_version, proxy_path = find_latest_version_for_step(asset_dir, asset_name, "PROXY")

        if proxy_path:
            open_existing_scene(proxy_path)
            stamp_asset_metadata(film_name, category, asset_name, current_step["name"], display_name, asset_id)
            save_path = os.path.join(asset_dir, f"{asset_name}_{step_code}_{display_name}_v1.mb")
            save_scene(save_path)
            log(f"Duplicated Proxy v{proxy_version} into Modeling: {save_path}")
            log("Assets.py completed successfully")
            return True

        # No rig/camera/frame-range setup needed the way assignments have
        # -- an asset IS the thing being built, it doesn't reference
        # anything else in.
        cmds.file(new=True, force=True)
        stamp_asset_metadata(film_name, category, asset_name, current_step["name"], display_name, asset_id)

        save_path = os.path.join(asset_dir, f"{asset_name}_{step_code}_{display_name}_v1.mb")
        save_scene(save_path)
        log(f"Created fresh asset file: {save_path}")
        log("Assets.py completed successfully")
        return True

    except Exception as e:
        log(f"ERROR: Unhandled exception: {e}")
        return False


if __name__ == "__main__":
    import sys
    _login_name = sys.argv[1] if len(sys.argv) > 1 else None
    _asset_id = sys.argv[2] if len(sys.argv) > 2 else None
    run(login_name=_login_name, asset_id=_asset_id)
