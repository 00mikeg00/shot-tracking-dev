"""
SaveNextVersion.py
UC GAA Shot Tracker — "Incremental Save" shelf button

Saves the current scene as the next version, preserving whatever extension
the currently open scene already has (.ma for assignments, .mb for capstone
film shots -- see CapstoneLayout.save_scene()/CapstoneAnimation.py for why
film shots require .mb). A previous version of this tool hardcoded .mb
regardless of the scene's actual extension, then a later fix hardcoded .ma
instead -- both silently forked a scene's version history into two file
types that Assignments.py's own version scanning, the Capstone*.py modules'
version scanning, the dashboard's "Saved: vN" indicator, and
GAAPlayblastTool_V7 never look for, since each of those only scans for one
specific extension. Preserving the open scene's own extension is the only
way this tool can't silently fork either convention.

find_latest_scene() below is a local, extension-parameterized copy of
Assignments.find_latest_scene() (which is hardcoded to .ma) -- deploy/
tools are each self-contained, so this doesn't reach into Assignments.py's
internals, and it needs a signature Assignments' own version doesn't have
anyway.
"""

import os
import re
import maya.cmds as cmds


def find_latest_scene(save_dir, base_name, ext):
    """
    Returns (version, path) for the highest existing version of this
    scene under the flat, step-agnostic convention ({base}_v{N}{ext}), or
    (0, None) if none exist yet. ext-parameterized so it works for both
    assignments' .ma and capstone film shots' .mb.
    """
    pattern = re.compile(rf"^{re.escape(base_name)}_v(\d+){re.escape(ext)}$", re.IGNORECASE)
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
        cmds.warning(f"Could not scan {save_dir} for existing versions: {e}")
    return highest, highest_path


def save_next_version():
    current_path = cmds.file(q=True, sn=True)
    if not current_path:
        cmds.warning("Please save the current scene first before running versioning.")
        return

    directory, filename = os.path.split(current_path)
    base, ext = os.path.splitext(filename)

    match = re.match(r"(.+)_v\d+$", base, re.IGNORECASE)
    if not match:
        cmds.warning(f"Filename must end with _v<number> to version correctly (e.g., SceneName_v1{ext or '.ma'})")
        return

    base_name = match.group(1)

    existing_version, _ = find_latest_scene(directory, base_name, ext)
    next_version = existing_version + 1
    new_filename = f"{base_name}_v{next_version}{ext}"
    new_path = os.path.join(directory, new_filename)

    confirm = cmds.confirmDialog(
        title="Confirm Save Version",
        message=f"Are you sure you want to save as:\n\n{new_filename}?",
        button=["Yes", "Cancel"],
        defaultButton="Yes",
        cancelButton="Cancel",
        dismissString="Cancel"
    )
    if confirm != "Yes":
        return

    try:
        cmds.file(rename=new_path)
        if ext.lower() == ".mb":
            # Explicit type= required for .mb -- unlike .ma, Maya does NOT
            # infer mayaBinary from the extension alone (see
            # CapstoneLayout.save_scene()).
            cmds.file(save=True, force=True, type="mayaBinary")
        else:
            # No explicit type= -- Maya infers mayaAscii from the .ma
            # extension just set above, same as a plain File > Save. An
            # explicit type="mayaAscii" makes Maya treat this as a
            # declared format change, which it refuses on a scene
            # containing "unknown" node data (e.g. a referenced rig using
            # a plugin outside pluginPrefs.mel's autoload list) -- see
            # Assignments.save_scene() for the confirmed repro.
            cmds.file(save=True, force=True)
        cmds.inViewMessage(amg=f"Saved <hl>{new_filename}</hl>", pos="topCenter", fade=True)
    except Exception as e:
        cmds.warning(f"Failed to save next version: {e}")
