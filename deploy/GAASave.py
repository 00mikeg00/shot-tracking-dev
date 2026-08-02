"""
GAASave.py
UC GAA Shot Tracker -- "GAA Save" shelf button + Alt+S hotkey

Saves the current scene as the next version of its current step, using the
step-based naming convention:

    {assignment_filename}_{display_name}_{STEP_CODE}_V###.ma
    e.g. BallBounce_Meredith Burgess_BL_V001.ma

All step/lock business logic (which step is "current", version scanning,
lock/unlock API calls, scene identity resolution) lives in Assignments.py
and is shared with Assignments.run() (the silent launcher-triggered flow)
and GAAOpen.py -- this file is a thin PySide6 UI layer over it, so all
three tools always agree on step derivation and naming.

Two entry points:
  - save_with_prompt(): the shelf button. Shows the "Lock this step?"
    prompt (PySide6/shiboken6 -- Maya 2026 ships PySide6 natively for both
    interactive Maya and mayapy, unlike the older PySide2).
  - save_silent(): the Alt+S hotkey. No prompt, no lock -- just versions.
    Locked-step protection still applies; only the "ask about locking"
    step is skipped.
Both funnel through _do_save() so there's exactly one save/versioning
implementation.

register_hotkey() binds Alt+S to save_silent(). It's called from
Assignments.py at the end of every successful run (see the two call sites
there) rather than from userSetup.mel, since that file is explicitly
hands-off per deployment policy and hotkey state isn't managed by the
installer anyway (no hotkeys.mhk in Install_UC_TOOLS_FALL_2026.bat) --
registering at runtime on every launch is idempotent and self-healing.
"""

import os

import maya.cmds as cmds
import maya.OpenMayaUI as omui
from PySide6 import QtWidgets
import shiboken6

import Assignments


# --- Qt plumbing ------------------------------------------------------

def _maya_main_window():
    ptr = omui.MQtUtil.mainWindow()
    if ptr is None:
        return None
    return shiboken6.wrapInstance(int(ptr), QtWidgets.QWidget)


def _error_dialog(title, message):
    box = QtWidgets.QMessageBox(_maya_main_window())
    box.setIcon(QtWidgets.QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    box.exec()


class _LockPromptDialog(QtWidgets.QDialog):
    def __init__(self, step_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GAA Save")
        self.setFixedWidth(300)
        self.lock_checked = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(f"Save {step_name}?"))

        self.lock_checkbox = QtWidgets.QCheckBox("Lock this step when done")
        layout.addWidget(self.lock_checkbox)

        button_row = QtWidgets.QHBoxLayout()
        save_btn = QtWidgets.QPushButton("Save")
        cancel_btn = QtWidgets.QPushButton("Cancel")
        button_row.addWidget(save_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

        save_btn.clicked.connect(self._on_save)
        cancel_btn.clicked.connect(self.reject)
        save_btn.setDefault(True)

    def _on_save(self):
        self.lock_checked = self.lock_checkbox.isChecked()
        self.accept()


def _prompt_lock_checkbox(step_name):
    """Returns True/False for the lock choice, or None if canceled."""
    dialog = _LockPromptDialog(step_name, parent=_maya_main_window())
    if dialog.exec() == QtWidgets.QDialog.Accepted:
        return dialog.lock_checked
    return None


def _prompt_locked_step(step):
    """Returns True if the user chose to self-unlock, else False."""
    box = QtWidgets.QMessageBox(_maya_main_window())
    box.setIcon(QtWidgets.QMessageBox.Information)
    box.setWindowTitle("Step Locked")
    box.setText(
        f"{step['name']} is locked and can't be saved over.\n\n"
        f"Locked by {step['locked_by'] or 'unknown'} at {step['locked_at'] or 'unknown time'}.\n\n"
        "You can unlock it yourself if you need to keep working on it."
    )
    unlock_btn = box.addButton("Unlock", QtWidgets.QMessageBox.ActionRole)
    box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() == unlock_btn


# --- Core save ------------------------------------------------------------

def _do_save(prompt_for_lock):
    context, assignment, login_name = Assignments.resolve_scene_context()
    if not assignment:
        _error_dialog(
            "No Session Found",
            "Could not determine which assignment this scene belongs to.\n\n"
            "Click OPEN on an assignment in Shot Tracker first."
        )
        return

    class_name = context["class"]["name"]
    semester = context["class"].get("semester")
    display_name = context["user"]["display_name"]
    individual_assignment_id = assignment["individual_assignment_id"]

    if not semester:
        cmds.warning("Session context has no semester -- click OPEN in Shot Tracker again first.")
        return

    steps = Assignments.fetch_steps_status(individual_assignment_id)
    if steps is None:
        _error_dialog("Shot Tracker Unreachable", "Could not check step lock status. Save canceled.")
        return

    step = Assignments.resolve_current_step(steps)
    if step is None:
        cmds.warning("This assignment has no steps configured.")
        return

    if step["locked"]:
        if _prompt_locked_step(step):
            success, payload = Assignments.unlock_step(individual_assignment_id, step["name"], login_name)
            if success:
                cmds.inViewMessage(amg=f"<hl>{step['name']} unlocked</hl> -- run GAA Save again to continue.", pos="topCenter", fade=True)
            else:
                _error_dialog("Unlock Failed", payload.get("error", "Unknown error"))
        return

    save_dir = Assignments.build_save_dir(semester, class_name)
    base_name = f"{assignment['filename']}_{display_name}"

    if step["short_code"] in Assignments.FILE_VERSIONED_STEP_CODES:
        existing_version, _ = Assignments.find_latest_step_scene(save_dir, base_name, step["short_code"])
        next_version = existing_version + 1
        save_path = os.path.join(save_dir, f"{base_name}_{step['short_code']}_V{next_version:03d}.ma")
    else:
        # No file-versioned steps for this assignment's step model -- keep
        # the flat, step-agnostic convention Assignments.py's legacy flow
        # already uses.
        existing_version, _ = Assignments.find_latest_scene(save_dir, base_name)
        next_version = existing_version + 1
        save_path = os.path.join(save_dir, f"{base_name}_v{next_version}.ma")

    do_lock = False
    if prompt_for_lock:
        choice = _prompt_lock_checkbox(step["name"])
        if choice is None:
            return  # user canceled -- nothing saved
        do_lock = choice

    Assignments.stamp_scene_metadata(
        class_name, assignment["name"], individual_assignment_id, semester, display_name
    )
    Assignments.save_scene(save_path)
    cmds.inViewMessage(amg=f"Saved <hl>{os.path.basename(save_path)}</hl>", pos="topCenter", fade=True)

    if do_lock:
        success, payload = Assignments.lock_step(individual_assignment_id, step["name"], login_name)
        if not success:
            _error_dialog("Lock Failed", f"Saved, but could not lock the step on Shot Tracker:\n{payload.get('error', 'unknown error')}")
            return

        cmds.inViewMessage(amg=f"<hl>{step['name']} locked</hl>", pos="topCenter", fade=True)

        # Locking a step means there's nothing left to do in this scene --
        # advance straight into the next one instead of leaving the
        # student sitting in a file they can no longer save over.
        next_step = Assignments.find_next_step(steps, step)
        if next_step is None:
            return  # locked the last step (Polish) -- nothing further to open

        opened, action, next_path = Assignments.open_or_create_step(
            steps, next_step, save_dir, base_name, class_name,
            assignment["name"], assignment, semester, display_name, individual_assignment_id
        )
        if opened:
            verb = "Opened" if action == "opened" else "Created"
            cmds.inViewMessage(amg=f"<hl>{verb} {next_step['name']}</hl>: {os.path.basename(next_path)}", pos="topCenter", fade=True)
        else:
            cmds.warning(f"Locked {step['name']}, but could not open {next_step['name']} automatically -- use GAA Open.")


# --- Entry points ---------------------------------------------------------

def save_with_prompt():
    """Shelf button entry point."""
    _do_save(prompt_for_lock=True)


def save_silent():
    """Alt+S hotkey entry point -- no lock prompt, no locking, just versions."""
    _do_save(prompt_for_lock=False)


def register_hotkey():
    """
    Binds Alt+S to save_silent(). Idempotent -- safe to call on every
    Maya launch (cmds.nameCommand/hotkey just reassign, they don't
    duplicate or error on repeat calls).
    """
    cmds.nameCommand(
        "gaaSaveSilentCommand",
        annotation="GAA Save (silent, no lock)",
        command='python("import GAASave; GAASave.save_silent()")'
    )
    cmds.hotkey(keyShortcut="s", altModifier=True, name="gaaSaveSilentCommand")


def run():
    save_with_prompt()


if __name__ == "__main__":
    run()
