"""
GAA_FixAssignmentFile.py
UC GAA Shot Tracker — Fix a manually-created assignment scene

For students who built a scene themselves in Maya (referenced rigs by
hand, saved with the wrong name/location) instead of using Shot Tracker's
OPEN button. Lets them pick which assignment the scene is actually for,
then re-identifies and relocates it using the exact same conventions
Assignments.py uses — without touching anything already in the scene.
Rigs, camera, animation stay exactly as the student left them; only the
scene's identity tags and save location get corrected.

Replaces GAA_Assignments.py's add_metadata_and_rename_ui(), which is no
longer compatible with the current system:
  - saved .mb, but the current system's version scanning and dashboard
    "Saved: vN" indicator only look for .ma
  - named files by Windows login instead of the student's display name
  - saved back to wherever the scene already happened to be, never the
    real network path
  - never set GAA_individual_assignment_id, which the current submission
    flow (GAAPlayblastTool_V7) requires

Depends on Assignments.py already being on the Maya script path
(C:/Cincy/scripts) — reuses its session-context loading, save-path
building, version scanning, metadata stamping, and save logic directly
rather than re-implementing them, so there's exactly one definition of
"the correct filename/path/tags" instead of two that can drift apart.
"""

import os
import getpass
import maya.cmds as cmds

import Assignments


def get_login_name():
    return getpass.getuser()


def launch_fix_ui():
    login_name = get_login_name()
    context = Assignments.load_session_context(login_name)

    if not context:
        cmds.confirmDialog(
            title="No Session Found",
            message=(
                "No Shot Tracker session found for this login.\n\n"
                "Click OPEN on any assignment in Shot Tracker first — "
                "that's what tells this tool which class and assignments "
                "you have."
            ),
            button=["OK"]
        )
        return

    assignments = context.get("assignments", [])
    if not assignments:
        cmds.confirmDialog(
            title="No Assignments Found",
            message="No assignments found in your current Shot Tracker session.",
            button=["OK"]
        )
        return

    if cmds.window("gaaFixWin", exists=True):
        cmds.deleteUI("gaaFixWin")

    win = cmds.window("gaaFixWin", title="Fix Assignment File", widthHeight=(360, 190))
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, columnOffset=("both", 12))

    cmds.text(label=" ", height=4)
    cmds.text(label=f"Class: {context['class']['name']}", align="left", font="boldLabelFont")
    cmds.text(label="This won't touch anything in your scene — only its", align="left")
    cmds.text(label="name and save location will be corrected.", align="left")
    cmds.text(label=" ", height=4)
    cmds.text(label="Which assignment is this?", align="left")
    assignment_menu = cmds.optionMenu("gaaFixAssignmentMenu")
    for a in assignments:
        cmds.menuItem(label=a["name"], parent=assignment_menu)
    cmds.text(label=" ", height=4)

    def on_apply(*_):
        selected_name = cmds.optionMenu(assignment_menu, q=True, value=True)
        assignment = next((a for a in assignments if a["name"] == selected_name), None)
        if not assignment:
            cmds.warning(f"Could not find assignment '{selected_name}' in session context.")
            return

        class_name = context["class"]["name"]
        semester = context["class"].get("semester")
        display_name = context["user"]["display_name"]

        if not semester:
            cmds.warning("Session context has no semester — click OPEN in Shot Tracker again first.")
            return

        save_dir = Assignments.build_save_dir(semester, class_name)
        base_name = f"{assignment['filename']}_{display_name}"

        existing_version, _ = Assignments.find_latest_scene(save_dir, base_name)
        next_version = existing_version + 1
        save_path = os.path.join(save_dir, f"{base_name}_v{next_version}.ma")

        Assignments.stamp_scene_metadata(
            class_name,
            assignment["name"],
            assignment["individual_assignment_id"],
            semester,
            display_name
        )
        Assignments.save_scene(save_path)

        cmds.confirmDialog(
            title="Fixed",
            message=f"Scene saved and tagged correctly:\n\n{save_path}",
            button=["OK"]
        )
        if cmds.window("gaaFixWin", exists=True):
            cmds.deleteUI("gaaFixWin")

    cmds.button(label="Fix and Save", command=on_apply, height=32)
    cmds.setParent("..")
    cmds.showWindow(win)


def run():
    launch_fix_ui()


if __name__ == "__main__":
    run()
