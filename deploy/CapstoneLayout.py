# CapstoneLayout.py
# UC GAA Shot Tracker — silent Maya scene/shot Layout setup for the capstone
# film pipeline. Invoked by launcher.py (action=scene_layout / shot_layout)
# after it has written the corresponding session context file. No shelf
# button, no in-Maya picker — every film/scene/shot/asset choice was already
# made by the Layout Coordinator in the dashboard config editor and/or
# resolved server-side by capstone_routes.py; this module just executes it.
#
# Both run() and run_shot() stay silent like Assignments.run(): no dialogs,
# no prompts, every failure logged and returned as False rather than raised.
#
# Filename convention matches the one already live in GAAPlayblastTool_V7.py
# (is_film_scene()) and review_routes.py's review-clip glob patterns:
#   {film}_{scene:3d}_{STEP}_{user}_v{n}.mb          (scene-level)
#   {film}_{scene:3d}_{shot:3d}_{STEP}_{user}_v{n}.mb (shot-level)
# STEP is the short code (LAY), lowercase "v", no zero-padding on the
# version number — NOT the "_V#"/full-word-step convention floated in the
# original capstone design doc, which would have broken is_film_scene()'s
# 6-part parser and every existing glob pattern keyed off it.

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

STEP_CODE = "LAY"

# capstone_routes.py's SCENE_ASSET_CATEGORIES today ("Sets", "Character/Rigs")
# — kept here only as a comment for context; the actual category list to
# reference comes straight off the "assets" dict the server already sent,
# so this module doesn't need to hard-code it.

# Character/Rigs assets are referenced by their PROXY file here, never the
# production (Modeling/Texture-Surface/Rigging) file — the proxy is meant
# to be used ONLY for Layout; Animation is what references the Shot-Ready
# rig instead (see CapstoneAnimation.py). Mirrors
# Assets.py:CATEGORY_FOLDER_MAP/get_asset_dir/find_latest_version_for_step
# — duplicated rather than imported since deploy/ tools are each
# self-contained.
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


def get_asset_production_dir(film_name, category, asset_name):
    folder = CATEGORY_FOLDER_MAP.get(category)
    if not folder:
        return None
    return os.path.join(ASSET_ROOT, film_name, "Assets", folder, asset_name)


def find_latest_proxy_version(asset_dir, asset_name):
    """Highest version among files tagged _PROXY_ for this asset -- see Assets.py's find_latest_version_for_step()."""
    safe_name = re.escape(asset_name).replace(r"\ ", r"[ _]")
    pattern = re.compile(rf"^{safe_name}_PROXY_.*?_v(\d+)\.(ma|mb)$", re.IGNORECASE)

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
        log(f"WARNING: Could not list {asset_dir} for proxy version scan: {e}")
    return highest, highest_path

_log_file = None


# ── Logging ───────────────────────────────────────────────────
def _init_log():
    global _log_file
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_file = os.path.join(LOG_DIR, f"capstone_layout_{timestamp}.log")


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
def load_scene_session(login_name):
    session_file = os.path.join(SESSIONS_PATH, f"{login_name}_scene_layout_context.json")
    if not os.path.isfile(session_file):
        log(f"ERROR: Scene layout session context not found: {session_file}")
        return None
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"ERROR: Could not read scene layout session context {session_file}: {e}")
        return None


def load_shot_session(login_name):
    session_file = os.path.join(SESSIONS_PATH, f"{login_name}_shot_layout_context.json")
    if not os.path.isfile(session_file):
        log(f"ERROR: Shot layout session context not found: {session_file}")
        return None
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"ERROR: Could not read shot layout session context {session_file}: {e}")
        return None


# ── Naming / path helpers ─────────────────────────────────────
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


def pad3(number):
    return str(number).zfill(3)


def scene_dir(film_name, scene_number):
    return os.path.join(FILMS_ROOT, film_name, pad3(scene_number))


def shot_dir(film_name, scene_number, shot_number):
    return os.path.join(scene_dir(film_name, scene_number), pad3(shot_number))


def find_latest_version(directory, base_name):
    """
    Highest existing {base_name}_v{N}.mb in directory, as (version, path),
    or (0, None) if none exist yet. base_name already has the step code and
    user baked in (see build_base_name), so this only ever matches this
    specific film/scene[/shot]/step/user's own version family.
    """
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


def find_latest_version_any_user(directory, film_name, scene_number, step_code):
    """
    Highest {film}_{scene}_{step}_*_v{N}.mb across ALL users in directory —
    used only to find "the" scene Layout file when copying into a new shot
    Layout. Scene Layout is a single shared file per scene (one Layout
    artist places the whole set), so unlike per-user assignment files there
    is no student-scoped base_name to key off; whoever last saved highest
    wins, matching how find_carry_forward_source picks "the" prior file in
    Assignments.py.
    """
    prefix = f"{film_name}_{pad3(scene_number)}_{step_code}_"
    pattern = re.compile(
        rf"^{re.escape(prefix)}.+_v(\d+)\.mb$", re.IGNORECASE
    )
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
        log(f"WARNING: Could not list {directory} for scene layout scan: {e}")
    return highest, highest_path


def build_scene_base_name(film_name, scene_number, display_name):
    return f"{film_name}_{pad3(scene_number)}_{STEP_CODE}_{display_name}"


def build_shot_base_name(film_name, scene_number, shot_number, display_name):
    return f"{film_name}_{pad3(scene_number)}_{pad3(shot_number)}_{STEP_CODE}_{display_name}"


# ── Maya scene operations ────────────────────────────────────
def reference_assets(assets_by_category, film_name):
    """
    Reference-in every asset the server resolved for this scene (today:
    Sets + Character/Rigs, per capstone_routes.py's SCENE_ASSET_CATEGORIES).
    This ports the "reference known assets by config-resolved path" idea
    from the removed GAA_FilmCreateShot.py's reference_items(), minus the
    Maya confirmDialog picker and minus that script's translate-offset
    positioning — the original script's source wasn't available in this
    session to port verbatim, so offsets are NOT applied here. Flagging
    this explicitly: if scene assets need config-driven placement (not just
    referencing at the origin), that logic still needs to be ported once
    the original script is available.

    Character/Rigs is special-cased: the server-provided file_path points
    at the asset's production file (whatever Modeling/Texture-Surface/
    Rigging currently has), but Layout must ONLY ever reference the Proxy
    file — resolved directly here rather than trusted from the server, by
    scanning that asset's own folder for its highest _PROXY_-tagged file.
    If no proxy exists yet, the asset is skipped (logged, not silently
    substituted with the production file) — referencing the real rig into
    Layout is exactly what this is meant to prevent.
    """
    used_namespaces = set()
    for category, items in assets_by_category.items():
        for item in items:
            name = item.get("name") if isinstance(item, dict) else item

            if category == "Character/Rigs":
                asset_dir = get_asset_production_dir(film_name, category, name)
                if not asset_dir:
                    log(f"ERROR: No folder mapping for category '{category}'; skipping '{name}'")
                    continue
                version, path = find_latest_proxy_version(asset_dir, name)
                if not path:
                    log(f"WARNING: No Proxy file exists yet for Character/Rigs asset '{name}'; skipping (Layout only ever references Proxy, never the production file)")
                    continue
                log(f"Resolved Proxy for '{name}': v{version}")
            else:
                path = item.get("file_path") if isinstance(item, dict) else item
                if not path:
                    log(f"WARNING: No file_path for asset '{name}' in category '{category}'; skipping")
                    continue

            if not os.path.isfile(path):
                log(f"ERROR: Asset not found on disk: {path}")
                continue

            base = sanitize_namespace(os.path.splitext(os.path.basename(path))[0])
            ns = unique_namespace(base, used_namespaces)

            cmds.file(path, reference=True, namespace=ns, ignoreVersion=True)
            log(f"Referenced {category} asset: {path} (namespace={ns})")


# Camera Framing (Edit Layout Config's per-shot dropdown, shots.camera_framing)
# -> focal length in mm. Matches films_routes.py's CAMERA_FRAMING_OPTIONS
# exactly ("Medium", not "MED").
FRAMING_TO_FOCAL_LENGTH = {
    "Wide": 28,
    "Full": 35,
    "Cowboy": 35,
    "Medium": 35,
    "MCU": 50,
    "CU": 50,
    "ECU": 80,
}
DEFAULT_FOCAL_LENGTH = 35


def add_shot_camera(shot_number, camera_framing=None):
    """
    Same default camera pattern as Assignments.add_camera() (name + fixed
    translate + Four View layout) — reused rather than reinvented, per the
    design doc's explicit ask to check for an existing camera-add
    convention before writing a new one. Focal length is set from the
    shot's Camera Framing (Edit Layout Config), falling back to
    DEFAULT_FOCAL_LENGTH if framing wasn't set on the shot yet or doesn't
    match a known option.
    """
    base = sanitize_namespace(f"shot_{shot_number}") + "_cam"
    cam_transform, cam_shape = cmds.camera(name=base)
    cmds.xform(cam_transform, worldSpace=True, translation=(0, 30, 90))
    log(f"Created camera: {cam_transform} at (0, 30, 90)")

    focal_length = FRAMING_TO_FOCAL_LENGTH.get(camera_framing, DEFAULT_FOCAL_LENGTH)
    cmds.setAttr(f"{cam_shape}.focalLength", focal_length)
    if camera_framing in FRAMING_TO_FOCAL_LENGTH:
        log(f"Set focal length to {focal_length}mm for Camera Framing '{camera_framing}'")
    else:
        log(f"WARNING: Camera Framing '{camera_framing}' not set/recognized; using default {focal_length}mm")

    set_four_view_layout(cam_transform)
    return cam_transform


def set_shot_frame_range(frame_count):
    """
    Applies the shot's current frame_count (Edit Layout Config, never
    locked -- see films_routes.save_shot_frame_count) as a 1-to-frame_count
    playback range. Unlike Camera Framing (set once, at shot Layout
    creation, since it's frozen once approved), this is called on EVERY
    open/create -- see run_shot() -- so a coordinator revising it later
    actually propagates instead of only ever applying to the first version.
    No-op if frame_count isn't set yet.
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


def set_four_view_layout(camera_name):
    """
    Identical to Assignments.set_four_view_layout() — see that module for
    the panel-geometry reasoning. Duplicated rather than imported since
    deploy/ tools are each self-contained (matches the existing
    Assignments.py/GAASave.py/GAAOpen.py split, not a new pattern).
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
    """Same tolerant-open handling as Assignments.open_existing_scene()."""
    try:
        cmds.file(path, open=True, force=True, ignoreVersion=True)
    except RuntimeError as e:
        log(f"WARNING: Non-fatal errors while opening {path}: {e}")
        cmds.file(rename=path)


def stamp_scene_metadata(film_name, scene_number, step_name, display_name,
                          scene_id=None, shot_id=None, shot_number=None):
    """
    Same idea as Assignments.stamp_scene_metadata() — tags identity onto
    the scene via fileInfo so GAAPlayblastTool_V7.py and future capstone
    tools can read it back without parsing the filename or touching the DB
    directly. GAA_scene_id/GAA_shot_id let a later "open whatever this scene
    belongs to" flow resolve the DB row the same way
    GAA_individual_assignment_id does for assignments.
    """
    cmds.fileInfo("GAA_film", film_name)
    cmds.fileInfo("GAA_scene_number", str(scene_number))
    cmds.fileInfo("GAA_step", step_name)
    cmds.fileInfo("GAA_display_name", display_name)
    if scene_id is not None:
        cmds.fileInfo("GAA_scene_id", str(scene_id))
    if shot_id is not None:
        cmds.fileInfo("GAA_shot_id", str(shot_id))
    if shot_number is not None:
        cmds.fileInfo("GAA_shot_number", str(shot_number))


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


def save_scene(save_path):
    """
    Explicit type="mayaBinary" — unlike Assignments.py's .ma files (where
    an explicit type= on save gets refused on "unknown" node data from
    referenced rigs), .mb is what the capstone convention requires
    (mayaBinary, confirmed in the design doc, not mayaAscii), so the type
    has to be stated; Maya won't infer mayaBinary from a .mb extension the
    way it infers mayaAscii from .ma.
    """
    save_dir = os.path.dirname(save_path)
    os.makedirs(save_dir, exist_ok=True)
    cmds.file(rename=save_path)
    cmds.file(save=True, force=True, type="mayaBinary")
    log(f"Scene saved: {save_path}")


# ── Main: scene-level Layout ──────────────────────────────────
def run(login_name=None, scene_id=None):
    _init_log()
    log("=" * 50)
    log("CapstoneLayout.run() started (scene-level)")

    login_name = login_name or getpass.getuser()
    log(f"login_name={login_name} scene_id={scene_id}")

    try:
        context = load_scene_session(login_name)
        if not context:
            return False

        film_name = context["film_name"]
        scene_number = context["scene_number"]
        display_name = context["user"]["display_name"]
        directory = scene_dir(film_name, scene_number)
        base_name = build_scene_base_name(film_name, scene_number, display_name)

        log(f"Scene: {film_name} / scene {scene_number} | artist: {display_name}")

        existing_version, existing_path = find_latest_version(directory, base_name)

        if existing_path:
            open_existing_scene(existing_path)
            stamp_scene_metadata(film_name, scene_number, "Layout", display_name,
                                  scene_id=context["scene_id"])
            log(f"Opened existing scene Layout (v{existing_version}): {existing_path}")
            log("CapstoneLayout.run() completed successfully")
            return True

        # First open: fresh scene, reference in the scene's config-resolved
        # assets. No camera — per the design doc, camera isn't relevant
        # until per-shot Layout.
        cmds.file(new=True, force=True)
        reference_assets(context.get("assets", {}), film_name)
        stamp_scene_metadata(film_name, scene_number, "Layout", display_name,
                              scene_id=context["scene_id"])

        save_path = os.path.join(directory, f"{base_name}_v1.mb")
        save_scene(save_path)
        log(f"Created fresh scene Layout: {save_path}")
        log("CapstoneLayout.run() completed successfully")
        return True

    except Exception as e:
        log(f"ERROR: Unhandled exception in run(): {e}")
        return False


# ── Main: shot-level Layout ───────────────────────────────────
def run_shot(login_name=None, shot_id=None):
    _init_log()
    log("=" * 50)
    log("CapstoneLayout.run_shot() started (shot-level)")

    login_name = login_name or getpass.getuser()
    log(f"login_name={login_name} shot_id={shot_id}")

    try:
        context = load_shot_session(login_name)
        if not context:
            return False

        film_name = context["film_name"]
        scene_number = context["scene_number"]
        shot_number = context["shot_number"]
        display_name = context["user"]["display_name"]
        directory = shot_dir(film_name, scene_number, shot_number)
        base_name = build_shot_base_name(film_name, scene_number, shot_number, display_name)

        log(f"Shot: {film_name} / scene {scene_number} / shot {shot_number} | artist: {display_name}")

        existing_version, existing_path = find_latest_version(directory, base_name)

        if existing_path:
            # Subsequent opens: just open the latest version. Shot Layout
            # has no BL/BP/P sub-steps to pick among (see 1.1 findings) —
            # locking here is whole-step (approved -> moves to Animation),
            # so there's nothing to "resolve" beyond "does a file exist."
            open_existing_scene(existing_path)
            stamp_scene_metadata(film_name, scene_number, "Layout", display_name,
                                  scene_id=context["scene_id"], shot_id=shot_id,
                                  shot_number=shot_number)
            stamp_render_dimensions(context)
            set_shot_frame_range(context.get("frame_count"))
            log(f"Opened existing shot Layout (v{existing_version}): {existing_path}")
            log("CapstoneLayout.run_shot() completed successfully")
            return True

        if not context.get("scene_layout_done"):
            log("ERROR: Scene Layout is not marked done yet; shot Layout cannot be created")
            cmds.warning("Scene Layout for this scene isn't marked done yet — ask your Layout artist to finish and submit it first.")
            return False

        scene_directory = scene_dir(film_name, scene_number)
        _, scene_layout_path = find_latest_version_any_user(scene_directory, film_name, scene_number, STEP_CODE)
        if not scene_layout_path:
            log(f"ERROR: scene_layout_done is true but no scene Layout file found in {scene_directory}")
            cmds.warning("Scene Layout is marked done, but no scene Layout file could be found on disk. Contact your instructor.")
            return False

        # OS-level file copy, not cmds.file(i=True) -- importing a file
        # into an already-open scene flattens its nested references into
        # embedded geometry (confirmed via CapstoneAnimation.py's identical
        # copy-in step: an empty Reference Editor after import, despite
        # pose/position data surviving). Opening a file with references,
        # unlike importing one, preserves them correctly, so copying the
        # scene Layout file to the shot Layout path and opening THAT keeps
        # every reference (Sets/Props/Character Proxy) exactly as the
        # scene Layout had it. Still no live link back to the scene Layout
        # FILE itself -- it's a copy, not a reference to that file, so
        # future scene Layout edits still won't propagate here, per the
        # design doc's explicit "no live reference" call.
        save_path = os.path.join(directory, f"{base_name}_v1.mb")
        os.makedirs(directory, exist_ok=True)
        shutil.copyfile(scene_layout_path, save_path)
        open_existing_scene(save_path)
        log(f"Copied scene Layout file to shot Layout: {scene_layout_path} -> {save_path}")

        add_shot_camera(shot_number, camera_framing=context.get("camera_framing"))
        set_shot_frame_range(context.get("frame_count"))

        stamp_scene_metadata(film_name, scene_number, "Layout", display_name,
                              scene_id=context["scene_id"], shot_id=shot_id,
                              shot_number=shot_number)
        stamp_render_dimensions(context)

        save_scene(save_path)
        log(f"Created fresh shot Layout (copy of scene Layout): {save_path}")
        log("CapstoneLayout.run_shot() completed successfully")
        return True

    except Exception as e:
        log(f"ERROR: Unhandled exception in run_shot(): {e}")
        return False


if __name__ == "__main__":
    import sys
    _login_name = sys.argv[1] if len(sys.argv) > 1 else None
    if len(sys.argv) > 2 and sys.argv[2] == "--shot":
        run_shot(login_name=_login_name, shot_id=sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run(login_name=_login_name, scene_id=sys.argv[2] if len(sys.argv) > 2 else None)
