"""
SaveNextVersion.py
UC GAA Shot Tracker — "Incremental Save" shelf button

Saves the current scene as the next version, matching the current save
convention (.ma, not .mb — the previous version of this tool hardcoded
.mb regardless of the scene's actual extension, which silently forked a
scene's version history into two file types that Assignments.py's own
version scanning, the dashboard's "Saved: vN" indicator, and
GAAPlayblastTool_V7 never look for).

Depends on Assignments.py already being on the Maya script path
(C:/Cincy/scripts) — reuses its find_latest_scene() to determine the next
version from what's actually on disk, rather than trusting the currently
open filename's embedded number (which could be stale if a higher
version exists for any reason).
"""

import os
import re
import maya.cmds as cmds

import Assignments


def save_next_version():
    current_path = cmds.file(q=True, sn=True)
    if not current_path:
        cmds.warning("Please save the current scene first before running versioning.")
        return

    directory, filename = os.path.split(current_path)
    base, ext = os.path.splitext(filename)

    match = re.match(r"(.+)_v\d+$", base, re.IGNORECASE)
    if not match:
        cmds.warning("Filename must end with _v<number> to version correctly (e.g., SceneName_v1.ma)")
        return

    base_name = match.group(1)

    existing_version, _ = Assignments.find_latest_scene(directory, base_name)
    next_version = existing_version + 1
    new_filename = f"{base_name}_v{next_version}.ma"
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
        # No explicit type= -- Maya infers mayaAscii from the .ma extension
        # just set above, same as a plain File > Save. An explicit
        # type="mayaAscii" makes Maya treat this as a declared format
        # change, which it refuses on a scene containing "unknown" node
        # data (e.g. a referenced rig using a plugin outside
        # pluginPrefs.mel's autoload list) -- see Assignments.save_scene()
        # for the confirmed repro.
        cmds.file(save=True, force=True)
        cmds.inViewMessage(amg=f"Saved <hl>{new_filename}</hl>", pos="topCenter", fade=True)
    except Exception as e:
        cmds.warning(f"Failed to save next version: {e}")
