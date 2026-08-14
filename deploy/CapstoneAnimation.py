# CapstoneAnimation.py
# UC GAA Shot Tracker — silent Maya shot Animation setup for the capstone
# film pipeline. Invoked by launcher.py (action=shot_animation) after it
# has written {login_name}_shot_animation_context.json. Same silent
# contract as the other Capstone*.py modules: no dialogs, no prompts,
# failures logged and returned as False.
#
# Animation is its own top-level workflow step, coming after Blocking
# (Layout -> Blocking -> Animation -> Lighting), NOT a container for
# self-locked Blocking/Blocking Plus/Polish sub-steps the way an earlier
# iteration of this pipeline had it -- that model has been dropped per
# explicit product direction (no GAA-Save self-lock flow for this stage).
# Works exactly like CapstoneBlocking.py/CapstoneLighting.py: single
# continuously versioned file, gated on the PRIOR step's per-shot
# approval, coordinator approves this shot individually.
#
# Filename convention: {film}_{scene:3d}_{shot:3d}_ANIM_{user}_v{n}.mb --
# distinct step code from Layout (_LAY_) and Blocking (_BL_) by
# construction, so an Animation session can never save over either
# regardless of what's open in Maya.

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

STEP_CODE         = "ANIM"
BLOCKING_STEP_CODE = "BL"

# Mirrors CapstoneBlocking.py -- duplicated rather than imported, deploy/
# tools are each self-contained. Used to reference the Shot-Ready rig for
# each of the scene's configured Character/Rigs assets, alongside whatever
# the copied-in Blocking file already has.
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


# ── Naming / path helpers ─────────────────────────────────────
def pad3(number):
    return str(number).zfill(3)


def shot_dir(film_name, scene_number, shot_number):
    return os.path.join(FILMS_ROOT, film_name, pad3(scene_number), pad3(shot_number))


def build_base_name(film_name, scene_number, shot_number, display_name):
    # STEP_CODE ("ANIM") is always embedded here, so this name can never
    # collide with a "_LAY_" or "_BL_" filename in the same folder.
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


def find_latest_blocking_any_user(directory, film_name, scene_number, shot_number):
    """
    Highest {film}_{scene}_{shot}_BL_*_v{N}.mb in the shot folder -- same
    "pick globally highest version, not scoped to a specific user"
    reasoning as CapstoneBlocking's own Layout lookup.
    """
    prefix = f"{film_name}_{pad3(scene_number)}_{pad3(shot_number)}_{BLOCKING_STEP_CODE}_"
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
        log(f"WARNING: Could not list {directory} for blocking scan: {e}")
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


def get_referenced_asset_dirs():
    """
    Directories (normalized) of every file currently referenced into the
    open scene. Used to tell whether a given Character/Rigs asset already
    has a reference in the scene, regardless of which version was
    referenced -- so re-running reference_character_rigs() on an
    already-set-up scene doesn't create duplicate references.
    """
    try:
        paths = cmds.file(query=True, reference=True) or []
    except RuntimeError:
        paths = []
    return {os.path.normcase(os.path.normpath(os.path.dirname(p))) for p in paths}


def _rig_already_present(name, referenced_dirs, asset_dir_norm):
    """
    True if this rig is already in the scene, checked two ways: as a live
    reference (asset_dir_norm in referenced_dirs), or by namespace prefix
    (sanitize_namespace(asset_name) + "_RIG_"). Now that Blocking's file
    is copied to the Animation path and opened (not imported -- see
    run_shot()), its rig reference should always show up as a live
    reference; the namespace check is a defensive fallback kept from when
    this module used cmds.file(i=True), which silently flattened
    references into embedded geometry that the reference-only check
    couldn't see.
    """
    if asset_dir_norm in referenced_dirs:
        return True
    prefix = (sanitize_namespace(name) + "_RIG_").lower()
    try:
        all_namespaces = cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True) or []
    except RuntimeError:
        all_namespaces = []
    return any(ns.lower().startswith(prefix) for ns in all_namespaces)


def reference_character_rigs(character_rigs, film_name, skip_already_referenced=False):
    """
    References the Shot-Ready (highest _RIG_-tagged) file for each of the
    scene's configured Character/Rigs assets, ADDITIONALLY to whatever the
    copied-in Blocking file already has -- both coexist by design, not a
    swap. If an asset hasn't reached Rigging yet, it's skipped (logged)
    rather than referencing a Modeling/Texture-Surface WIP file.

    skip_already_referenced=True makes this safe to call whenever the rig
    might already be present -- every re-open of an existing Animation
    file, AND the very first creation (Blocking's already-posed rig comes
    along with the copy-in import, see _rig_already_present()): assets
    already in the scene are left alone, so only newly Shot-Ready assets
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

        if skip_already_referenced and _rig_already_present(
            name, referenced_dirs, os.path.normcase(os.path.normpath(asset_dir))
        ):
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
    cmds.fileInfo("GAA_step", "Animation")
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

    Also applies width/height to Maya's own Render Settings resolution
    and turns on the Resolution Gate mask on every non-default camera, so
    the viewport frames the same crop the playblast actually captures --
    GAAPlayblastTool_V7.py's playblast passes these same numbers straight
    to cmds.playblast() as raw pixel width/height, which stretches
    whatever the viewport happens to be showing rather than deriving it
    from the camera's own film-back aperture. Without this, composing a
    shot in the viewport (default camera aperture) and what actually gets
    captured (the film's real aspect ratio) can visibly differ.
    """
    width = context.get("render_width")
    height = context.get("render_height")
    if not (width and height):
        return

    cmds.fileInfo("GAA_render_width", str(width))
    cmds.fileInfo("GAA_render_height", str(height))

    cmds.setAttr("defaultResolution.width", width)
    cmds.setAttr("defaultResolution.height", height)
    cmds.setAttr("defaultResolution.pixelAspect", 1.0)
    cmds.setAttr("defaultResolution.deviceAspectRatio", width / float(height))

    for cam_shape in cmds.ls(type="camera"):
        cam_transform = cmds.listRelatives(cam_shape, parent=True)
        if not cam_transform or cam_transform[0] in ("persp", "top", "front", "side"):
            continue
        try:
            cmds.setAttr(f"{cam_shape}.displayResolution", True)
            cmds.setAttr(f"{cam_shape}.displayGateMask", True)
            cmds.setAttr(f"{cam_shape}.filmFit", 3)  # Overscan -- resolution gate stays fully visible, never clipped by the film-back aperture
        except RuntimeError:
            continue


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
    Path/basename always contain "_ANIM_" by construction (build_base_name),
    so this can never write to a "_LAY_"/"_BL_" filename even if something
    upstream passed a bad path.
    """
    save_dir = os.path.dirname(save_path)
    os.makedirs(save_dir, exist_ok=True)
    cmds.file(rename=save_path)
    cmds.file(save=True, force=True, type="mayaBinary")
    log(f"Scene saved: {save_path}")


# ── Main: shot Animation ──────────────────────────────────────
def run_shot(login_name=None, shot_id=None):
    """
    Per-shot, created once this shot's own Blocking is Approved or CUT (see
    "shot_blocking_approved" in the session context -- gate is per-shot).
    First open copies in the shot's own approved Blocking file, then
    references in any newly Shot-Ready Character Rigs. Subsequent opens
    just open the latest existing Animation file, backfilling any rigs
    that became Shot-Ready since the last open, same shape as the sub-step
    version this replaced.
    """
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
            reference_character_rigs(character_rigs, film_name, skip_already_referenced=True)
            set_shot_frame_range(frame_count)
            log(f"Opened existing Animation (v{existing_version}): {existing_path}")
            log("CapstoneAnimation.run_shot() completed successfully")
            return True

        if not context.get("shot_blocking_approved"):
            log("ERROR: This shot's Blocking is not approved (or CUT) yet; Animation cannot be created")
            cmds.warning("This shot's Blocking hasn't been approved yet — Animation can't start until it is.")
            return False

        _, blocking_path = find_latest_blocking_any_user(directory, film_name, scene_number, shot_number)
        if not blocking_path:
            log(f"ERROR: shot_blocking_approved is true but no Blocking file found in {directory}")
            cmds.warning("This shot's Blocking is approved, but no Blocking file could be found on disk for it. Contact your instructor.")
            return False

        # OS-level file copy, not cmds.file(i=True) -- confirmed by an
        # empty Reference Editor after import that Maya flattens nested
        # references into embedded geometry when importing a file into an
        # already-open scene (that's what produced the 21MB file: real
        # geometry baked in instead of a lightweight reference edge).
        # Opening a file with references, unlike importing one, preserves
        # them correctly -- same open_existing_scene() already relied on
        # everywhere else in these modules -- so copying Blocking's file
        # to the Animation path and opening THAT keeps every reference
        # (rig included) exactly as Blocking had it.
        save_path = os.path.join(directory, f"{base_name}_v1.mb")
        os.makedirs(directory, exist_ok=True)
        shutil.copyfile(blocking_path, save_path)
        open_existing_scene(save_path)
        log(f"Copied Blocking file to Animation: {blocking_path} -> {save_path}")

        # skip_already_referenced=True: the copy above already carries
        # Blocking's posed/keyframed rig over as a genuine live reference
        # now -- _rig_already_present() detects it and leaves it
        # completely untouched. This only adds a fresh reference for rigs
        # that weren't Shot-Ready yet at Blocking time.
        reference_character_rigs(character_rigs, film_name, skip_already_referenced=True)
        set_shot_frame_range(frame_count)

        stamp_scene_metadata(film_name, scene_number, shot_number, shot_id,
                              context["scene_id"], display_name)
        stamp_render_dimensions(context)

        save_scene(save_path)
        log(f"Created fresh Animation (copy of Blocking + referenced rigs): {save_path}")
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
