# CapstoneAssetSync.py
# UC GAA Shot Tracker — interactive "sync referenced assets to latest" tool
# for the capstone film pipeline. Unlike the other Capstone*.py modules
# (silent, launched fresh from the dashboard via launcher.py), this one is
# meant to run inside an ALREADY-OPEN scene via a shelf button: Maya
# references pin the exact file they were pointed at when added, so a
# Layout/Blocking/Animation/Lighting scene keeps referencing whatever
# asset version existed at reference time, forever, even after that asset
# ships a newer Proxy/Shot-Ready version. CapstoneLayout.py/
# CapstoneAnimation.py/CapstoneLighting.py only ever ADD a reference for an
# asset that isn't in the scene yet; none of them upgrade one that's
# already there. This tool lists every out-of-date reference in the
# current scene and lets the artist choose which to swap onto the latest
# version, via cmds.file(loadReference=...) so the reference node's
# namespace and any scene-side edits (transforms, etc.) survive the swap
# instead of a duplicate reference getting added alongside the old one.
#
# Invoke from a shelf button or the Script Editor:
#   import CapstoneAssetSync
#   CapstoneAssetSync.show_ui()

import os
import re

import maya.cmds as cmds

# ── Config ────────────────────────────────────────────────────
# Reverse of every other Capstone*.py module's CATEGORY_FOLDER_MAP --
# needed here because this tool has to go the other direction, folder name
# (parsed back out of a reference's own file path) -> category, not
# category -> folder. Keep in sync with CapstoneLayout.py/
# CapstoneAnimation.py/CapstoneBlocking.py/CapstoneLighting.py/Assets.py.
FOLDER_TO_CATEGORY = {
    "Sets": "Sets",
    "Rigs": "Character/Rigs",
    "Props_-_3D": "Props - 3D",
    "Props_-_2D": "Props - 2D",
    "LightRigs": "Light Rigs",
    "BGs": "BGs",
}

# Which tagged version counts as "latest" for a Character/Rigs reference
# depends on which pipeline stage this scene is at (GAA_step, stamped by
# whichever Capstone*.py module created/opened it): Layout only ever
# references the Proxy (CapstoneLayout.reference_assets()); Blocking,
# Animation, and Lighting all reference the Shot-Ready rig instead
# (CapstoneBlocking.py/CapstoneAnimation.py's reference_character_rigs()).
CHARACTER_RIG_TAG_BY_STEP = {
    "Layout": "PROXY",
    "Blocking": "RIG",
    "Animation": "RIG",
    "Lighting": "RIG",
}
LIGHT_RIG_TAG = "LGTRIG"

_log_file = None


# ── Logging ───────────────────────────────────────────────────
def _init_log():
    global _log_file
    import datetime
    log_dir = r"C:\Cincy\logs"
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_file = os.path.join(log_dir, f"capstone_asset_sync_{timestamp}.log")


def log(message):
    if _log_file is None:
        _init_log()
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    try:
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


# ── Version resolution ───────────────────────────────────────
def _find_latest_tagged(asset_dir, asset_name, tag):
    """Highest version among files tagged _{tag}_ for this asset -- same convention as every other Capstone*.py module's own Shot-Ready/Proxy lookup."""
    safe_name = re.escape(asset_name).replace(r"\ ", r"[ _]")
    pattern = re.compile(rf"^{safe_name}_{tag}_.*?_v(\d+)\.(ma|mb)$", re.IGNORECASE)
    highest, highest_path = 0, None
    try:
        for entry in os.listdir(asset_dir):
            match = pattern.match(entry)
            if match:
                version = int(match.group(1))
                if version > highest:
                    highest, highest_path = version, os.path.join(asset_dir, entry)
    except OSError as e:
        log(f"WARNING: Could not list {asset_dir}: {e}")
    return highest, highest_path


def _find_latest_generic(asset_dir, asset_name):
    """Highest version for this asset regardless of which step produced it, excluding Proxy -- mirrors Assets.py's find_latest_asset_version()."""
    safe_name = re.escape(asset_name).replace(r"\ ", r"[ _]")
    pattern = re.compile(rf"^{safe_name}.*?_v(\d+)\.(ma|mb)$", re.IGNORECASE)
    highest, highest_path = 0, None
    try:
        for entry in os.listdir(asset_dir):
            if "_PROXY_" in entry.upper():
                continue
            match = pattern.match(entry)
            if match:
                version = int(match.group(1))
                if version > highest:
                    highest, highest_path = version, os.path.join(asset_dir, entry)
    except OSError as e:
        log(f"WARNING: Could not list {asset_dir}: {e}")
    return highest, highest_path


# A referenced asset file always lives at
# ...\{film}\Assets\{folder}\{asset_name}\{filename} -- every
# Capstone*.py/Assets.py module saves into that exact layout, so the
# category, asset name, and asset directory can all be recovered straight
# from a live reference's own path without needing a session context or a
# call back to Shot Tracker.
_REF_PATH_RE = re.compile(
    r"[\\/](?P<film>[^\\/]+)[\\/]Assets[\\/](?P<folder>[^\\/]+)[\\/](?P<asset>[^\\/]+)[\\/](?P<filename>[^\\/]+)$",
    re.IGNORECASE
)
_VERSION_RE = re.compile(r"_v(\d+)\.(ma|mb)$", re.IGNORECASE)


def _parse_reference(ref_path):
    """
    Pulls {film, category, asset_name, current_version} out of a
    referenced file's path. Returns None for anything that isn't one of
    this pipeline's Assets/ references (e.g. a rig used ad hoc from
    outside Assets/) -- those are left alone, not flagged as out of date.
    """
    match = _REF_PATH_RE.search(ref_path)
    if not match:
        return None
    category = FOLDER_TO_CATEGORY.get(match.group("folder"))
    if not category:
        return None
    version_match = _VERSION_RE.search(match.group("filename"))
    return {
        "category": category,
        "asset_name": match.group("asset"),
        "asset_dir": os.path.dirname(ref_path),
        "current_version": int(version_match.group(1)) if version_match else 0,
    }


def find_outdated_references():
    """
    Scans every reference in the currently open scene and returns a list
    of dicts for the ones that aren't on the latest applicable version:
    {reference_node, current_path, current_version, latest_path,
    latest_version, category, asset_name}. Character/Rigs references are
    skipped (not flagged, not an error) if this scene's GAA_step tag is
    missing/unrecognized -- there's no safe way to tell whether Proxy or
    Shot-Ready is the right "latest" without it.
    """
    try:
        gaa_step = cmds.fileInfo("GAA_step", query=True)
        gaa_step = gaa_step[0] if gaa_step else None
    except RuntimeError:
        gaa_step = None

    try:
        ref_paths = cmds.file(query=True, reference=True) or []
    except RuntimeError:
        ref_paths = []

    outdated = []
    for ref_path in ref_paths:
        parsed = _parse_reference(ref_path)
        if not parsed:
            continue

        asset_dir = parsed["asset_dir"]

        if parsed["category"] == "Character/Rigs":
            tag = CHARACTER_RIG_TAG_BY_STEP.get(gaa_step)
            if not tag:
                log(f"Skipping '{parsed['asset_name']}': scene's GAA_step ('{gaa_step}') doesn't say whether Proxy or Shot-Ready applies")
                continue
            latest_version, latest_path = _find_latest_tagged(asset_dir, parsed["asset_name"], tag)
        elif parsed["category"] == "Light Rigs":
            latest_version, latest_path = _find_latest_tagged(asset_dir, parsed["asset_name"], LIGHT_RIG_TAG)
        else:
            latest_version, latest_path = _find_latest_generic(asset_dir, parsed["asset_name"])

        if not latest_path or latest_version <= parsed["current_version"]:
            continue

        try:
            ref_node = cmds.file(ref_path, query=True, referenceNode=True)
        except RuntimeError:
            log(f"WARNING: Could not resolve reference node for {ref_path}; skipping")
            continue

        outdated.append({
            "reference_node": ref_node,
            "current_path": ref_path,
            "current_version": parsed["current_version"],
            "latest_path": latest_path,
            "latest_version": latest_version,
            "category": parsed["category"],
            "asset_name": parsed["asset_name"],
        })

    return outdated


def _normalize_path(path):
    return os.path.normcase(os.path.normpath(path))


def update_references(items):
    """
    Swaps each reference node onto its latest file in place -- keeps the
    namespace and any scene-side edits, doesn't add a duplicate reference.
    force=True is required here (every other destructive cmds.file() call
    in this pipeline -- open=True, save=True -- passes it too): without
    it, Maya silently no-ops instead of prompting to confirm, since
    there's no dialog to answer in a script, and the swap never actually
    happens even though the command returns without raising. Verifies the
    reference's filename afterward rather than trusting a lack of
    exception, since that's exactly the failure mode this was missing.
    """
    updated, failed = [], []
    for item in items:
        try:
            cmds.file(item["latest_path"], loadReference=item["reference_node"],
                      force=True, ignoreVersion=True)

            actual_path = cmds.referenceQuery(item["reference_node"], filename=True, withoutCopyNumber=True)
            if _normalize_path(actual_path) != _normalize_path(item["latest_path"]):
                log(f"ERROR: Update for '{item['asset_name']}' did not take effect -- reference still points at {actual_path}")
                failed.append(item)
                continue

            log(f"Updated '{item['asset_name']}': v{item['current_version']} -> v{item['latest_version']} ({item['latest_path']})")
            updated.append(item)
        except RuntimeError as e:
            log(f"ERROR: Failed to update '{item['asset_name']}' to {item['latest_path']}: {e}")
            failed.append(item)
    return updated, failed


# ── UI ────────────────────────────────────────────────────────
def show_ui():
    """Lists every out-of-date reference in the current scene with a checkbox per row, and an Update Selected button."""
    _init_log()
    log("CapstoneAssetSync.show_ui() opened")

    outdated = find_outdated_references()

    from PySide6 import QtWidgets, QtCore
    import maya.OpenMayaUI as omui
    import shiboken6

    maya_main_window = shiboken6.wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)

    dialog = QtWidgets.QDialog(maya_main_window)
    dialog.setWindowTitle("Sync Assets to Latest")
    dialog.resize(560, 360)
    layout = QtWidgets.QVBoxLayout(dialog)

    if not outdated:
        layout.addWidget(QtWidgets.QLabel("Every referenced asset in this scene is already on its latest version."))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec_()
        return

    layout.addWidget(QtWidgets.QLabel(f"{len(outdated)} referenced asset(s) have a newer version available:"))

    table = QtWidgets.QTableWidget(len(outdated), 5)
    table.setHorizontalHeaderLabels(["Update", "Category", "Asset", "Current", "Latest"])
    table.horizontalHeader().setStretchLastSection(True)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

    checkboxes = []
    for row, item in enumerate(outdated):
        checkbox = QtWidgets.QCheckBox()
        checkbox.setChecked(True)
        checkbox_wrap = QtWidgets.QWidget()
        checkbox_layout = QtWidgets.QHBoxLayout(checkbox_wrap)
        checkbox_layout.addWidget(checkbox)
        checkbox_layout.setAlignment(QtCore.Qt.AlignCenter)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        table.setCellWidget(row, 0, checkbox_wrap)
        checkboxes.append(checkbox)

        table.setItem(row, 1, QtWidgets.QTableWidgetItem(item["category"]))
        table.setItem(row, 2, QtWidgets.QTableWidgetItem(item["asset_name"]))
        table.setItem(row, 3, QtWidgets.QTableWidgetItem(f"v{item['current_version']}"))
        table.setItem(row, 4, QtWidgets.QTableWidgetItem(f"v{item['latest_version']}"))

    table.resizeColumnsToContents()
    layout.addWidget(table)

    status_label = QtWidgets.QLabel("")
    layout.addWidget(status_label)

    button_row = QtWidgets.QHBoxLayout()
    update_btn = QtWidgets.QPushButton("Update Selected")
    close_btn = QtWidgets.QPushButton("Close")
    button_row.addStretch()
    button_row.addWidget(update_btn)
    button_row.addWidget(close_btn)
    layout.addLayout(button_row)

    close_btn.clicked.connect(dialog.close)

    def on_update_clicked():
        selected = [item for item, cb in zip(outdated, checkboxes) if cb.isChecked()]
        if not selected:
            status_label.setText("Nothing selected.")
            return
        updated, failed = update_references(selected)
        msg = f"Updated {len(updated)} asset(s)."
        if failed:
            msg += f" {len(failed)} failed -- see log."
        status_label.setText(msg)
        update_btn.setEnabled(False)

    update_btn.clicked.connect(on_update_clicked)

    dialog.exec_()


if __name__ == "__main__":
    show_ui()
