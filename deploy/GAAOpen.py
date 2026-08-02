"""
GAAOpen.py
UC GAA Shot Tracker -- "GAA Open" shelf button

Interactive, on-demand counterpart to Assignments.py's silent
launcher-triggered auto-open. Assignments.py itself stays exactly as
silent as it's always documented itself to be ("No UI: no dialogs, no
prompts") -- it runs the instant Maya launches, before a student's looked
at anything, and now just opens/creates the correct step-versioned file
automatically with no interaction. This file is where the interactive
picker actually lives: a shelf button a student clicks deliberately, safe
to show PySide6 dialogs from.

Flow: always shows a single picker listing every file-versioned step
(Blocking/Blocking Plus/Polish) in order, each row describing its own
state and the action clicking it will take:
  - Has a file, locked:   "{name} (locked)"          -> Unlock and Open
  - Has a file, unlocked: "{name}"                    -> Open
  - No file yet, and the step right before it is
    already locked (so it's legitimately reachable):  -> Open
    (this builds its first file via carry-forward from that locked
    predecessor, same as before)
  - No file yet, and the step right before it has a
    file but ISN'T locked yet:                        -> Lock {prev} and Open
    (this is the actual rule change: you can't jump ahead into a step
    until the one before it is explicitly locked -- previously the picker
    let you carry-forward into any later step regardless of whether the
    predecessor was "finished")
  - No file yet, and the step right before it also
    has no file (nothing to lock/carry from):         -> disabled
  - The very first step, no file yet at all:           -> Start (fresh scene)

The combo defaults to whatever resolve_current_step() would pick, so the
common case (open whatever you were last working on) is just accepting
the default and clicking the button -- but every step's real state is
visible up front instead of hidden behind a separate confirm dialog.

All business logic -- step derivation, version scanning, lock/unlock API
calls, rig/camera/frame-range setup -- lives in Assignments.py and is
shared with GAASave.py, so this file only owns the interactive UI.
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


class _StepPickerDialog(QtWidgets.QDialog):
    def __init__(self, rows, default_index, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Open Step")
        self.setFixedWidth(340)
        self._rows = rows
        self.chosen_row = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Which step do you want to open?"))

        self.combo = QtWidgets.QComboBox()
        for row in rows:
            self.combo.addItem(row["label"])
        model = self.combo.model()
        for i, row in enumerate(rows):
            if not row["enabled"]:
                item = model.item(i)
                item.setEnabled(False)
        self.combo.setCurrentIndex(default_index)
        layout.addWidget(self.combo)

        button_row = QtWidgets.QHBoxLayout()
        self.action_btn = QtWidgets.QPushButton()
        cancel_btn = QtWidgets.QPushButton("Cancel")
        button_row.addWidget(self.action_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

        self.combo.currentIndexChanged.connect(self._sync_action_button)
        self.action_btn.clicked.connect(self._on_confirm)
        cancel_btn.clicked.connect(self.reject)
        self.action_btn.setDefault(True)

        self._sync_action_button(self.combo.currentIndex())

    def _sync_action_button(self, index):
        row = self._rows[index]
        self.action_btn.setText(row["action"])
        self.action_btn.setEnabled(row["enabled"])

    def _on_confirm(self):
        self.chosen_row = self._rows[self.combo.currentIndex()]
        self.accept()


def _step_picker_dialog(rows, default_index):
    dialog = _StepPickerDialog(rows, default_index, parent=_maya_main_window())
    if dialog.exec() == QtWidgets.QDialog.Accepted:
        return dialog.chosen_row
    return None


# --- Row building -----------------------------------------------------------

def _build_step_rows(pickable_steps, save_dir, base_name):
    """
    One row per file-versioned step, in order_num order, each carrying
    the label/action text to show plus which operation ("open",
    "unlock_and_open", "lock_prev_and_open", or "disabled") selecting it
    and clicking the action button should perform.
    """
    rows = []
    prev_step = None
    prev_path = None

    for step in pickable_steps:
        _, path = Assignments.find_latest_step_scene(save_dir, base_name, step["short_code"])

        if path:
            if step["locked"]:
                label = f"{step['name']} (locked)"
                action = "Unlock and Open"
                op = "unlock_and_open"
            else:
                label = step["name"]
                action = "Open"
                op = "open"
            enabled = True
        elif prev_step is None:
            # First file-versioned step, nothing saved yet at all.
            label = f"{step['name']} -- hasn't started yet"
            action = "Start"
            op = "open"
            enabled = True
        elif prev_path:
            if prev_step["locked"]:
                label = f"{step['name']} -- hasn't started yet"
                action = "Open"
                op = "open"
            else:
                label = f"{step['name']} -- hasn't started yet"
                action = f"Lock {prev_step['name']} and Open"
                op = "lock_prev_and_open"
            enabled = True
        else:
            # The step before this one has no file either -- nothing
            # sensible to lock or carry forward from yet.
            label = f"{step['name']} -- hasn't started yet"
            action = "Complete earlier steps first"
            op = "disabled"
            enabled = False

        rows.append({"step": step, "label": label, "action": action, "op": op, "enabled": enabled, "prev_step": prev_step})
        prev_step = step
        prev_path = path

    return rows


# --- Shared open/create/lock helpers ---------------------------------------

def _unlock_and_open(steps, step, ia_id, login_name, save_dir, base_name, class_name, assignment_name, assignment, semester, display_name):
    """
    Unlocks step and opens it in one action, no confirmation dialog --
    selecting a row already labeled "(locked) -- Unlock and Open" and
    clicking the button is itself the informed choice. The unlock is
    still fully logged (actor/timestamp via Assignments.unlock_step), it
    just doesn't require a second click to authorize.
    """
    success, payload = Assignments.unlock_step(ia_id, step["name"], login_name)
    if not success:
        _error_dialog("Unlock Failed", payload.get("error", "Unknown error"))
        return
    cmds.inViewMessage(amg=f"<hl>{step['name']} unlocked</hl>", pos="topCenter", fade=True)
    _open_step(steps, step, save_dir, base_name, class_name, assignment_name, assignment, semester, display_name, ia_id)


def _lock_prev_and_open(steps, prev_step, target_step, ia_id, login_name, save_dir, base_name, class_name, assignment_name, assignment, semester, display_name):
    """
    Locks prev_step (finishing it) before opening/creating target_step.
    This is a workflow rule, not a technical prerequisite -- carry-forward
    itself doesn't care whether prev_step is locked -- but a student
    shouldn't be able to silently skip ahead into Polish while Blocking
    Plus is still nominally in progress; picking this row is the explicit
    "I'm done with {prev_step}, move me on" action.
    """
    success, payload = Assignments.lock_step(ia_id, prev_step["name"], login_name)
    if not success:
        _error_dialog("Lock Failed", payload.get("error", "Unknown error"))
        return
    cmds.inViewMessage(amg=f"<hl>{prev_step['name']} locked</hl>", pos="topCenter", fade=True)
    _open_step(steps, target_step, save_dir, base_name, class_name, assignment_name, assignment, semester, display_name, ia_id)


def _open_step(steps, step, save_dir, base_name, class_name, assignment_name, assignment, semester, display_name, ia_id):
    """
    Opens step's latest file, or creates it if none exists yet
    (carry-forward-or-fresh-scene, same logic GAASave.py's post-lock
    advance uses) -- one shared implementation via
    Assignments.open_or_create_step so both tools agree on this behavior.
    """
    success, action, path = Assignments.open_or_create_step(
        steps, step, save_dir, base_name, class_name, assignment_name,
        assignment, semester, display_name, ia_id
    )
    if not success:
        _error_dialog("Could Not Open Step", f"No frame range configured for '{assignment_name}'.")
        return
    verb = "Opened" if action == "opened" else "Created"
    cmds.inViewMessage(amg=f"{verb} <hl>{os.path.basename(path)}</hl>", pos="topCenter", fade=True)


# --- Core flow --------------------------------------------------------------

def open_with_prompt():
    context, assignment, login_name = Assignments.resolve_scene_context()
    if not assignment:
        _error_dialog(
            "No Session Found",
            "Could not determine which assignment to open.\n\n"
            "Click OPEN on an assignment in Shot Tracker first."
        )
        return

    class_name = context["class"]["name"]
    semester = context["class"].get("semester")
    display_name = context["user"]["display_name"]
    assignment_name = assignment["name"]
    ia_id = assignment["individual_assignment_id"]

    if not semester:
        cmds.warning("Session context has no semester -- click OPEN in Shot Tracker again first.")
        return

    save_dir = Assignments.build_save_dir(semester, class_name)
    base_name = f"{assignment['filename']}_{display_name}"

    steps = Assignments.fetch_steps_status(ia_id)
    if steps is None:
        _error_dialog("Shot Tracker Unreachable", "Could not check step status. Open canceled.")
        return

    pickable = sorted(
        (s for s in steps if s.get("short_code") in Assignments.FILE_VERSIONED_STEP_CODES),
        key=lambda s: s["order_num"]
    )
    if not pickable:
        cmds.warning("This assignment has no steps configured.")
        return

    rows = _build_step_rows(pickable, save_dir, base_name)

    current_step = Assignments.resolve_current_step(steps)
    default_index = next((i for i, r in enumerate(rows) if r["step"] is current_step), 0)

    chosen_row = _step_picker_dialog(rows, default_index)
    if chosen_row is None:
        return

    step = chosen_row["step"]
    op = chosen_row["op"]

    if op == "open":
        _open_step(steps, step, save_dir, base_name, class_name, assignment_name, assignment, semester, display_name, ia_id)
    elif op == "unlock_and_open":
        _unlock_and_open(steps, step, ia_id, login_name, save_dir, base_name, class_name, assignment_name, assignment, semester, display_name)
    elif op == "lock_prev_and_open":
        _lock_prev_and_open(steps, chosen_row["prev_step"], step, ia_id, login_name, save_dir, base_name, class_name, assignment_name, assignment, semester, display_name)


def run():
    open_with_prompt()


if __name__ == "__main__":
    run()
