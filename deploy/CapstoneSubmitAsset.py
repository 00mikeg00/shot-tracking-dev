# CapstoneSubmitAsset.py
# UC GAA Shot Tracker — "Submit" button for the asset pipeline (Modeling/
# Texture-Surface/Rigging/Proxy/Rig Creation etc., via deploy/Assets.py).
# Meant to run inside an ALREADY-OPEN asset scene via a shelf button, same
# invocation shape as CapstoneAssetSync.py.
#
# Resolves the currently open scene's asset/step from the GAA_asset_id/
# GAA_step fileInfo tags Assets.py already stamps on every save/open
# (stamp_asset_metadata()), then POSTs a "Submitted" status update to the
# exact same endpoint the web dashboard's status dropdown already uses
# (update_asset_step() in films_routes.py) -- so this goes through the
# identical crossflow cascade instead of a separate Maya-only status path
# that could drift out of sync with it.
#
# Shots are deliberately NOT covered by this tool -- shot status is set
# through the dashboard's own status dropdown (dashboard_films.js), not a
# Maya-side button, and Capstone*.py's own approval gates
# (shot_layout_approved/shot_blocking_approved/etc.) read that directly.
#
# Invoke from a shelf button or the Script Editor:
#   import CapstoneSubmitAsset
#   CapstoneSubmitAsset.show_ui()

import os

import maya.cmds as cmds
import requests

SHOT_TRACKER_URL = os.environ.get("SHOT_TRACKER_URL", "http://10.23.20.210:8000")


def _scene_tag(key):
    value = cmds.fileInfo(key, query=True)
    return value[0] if value else None


def fetch_asset_steps(asset_id):
    """Same call/shape as Assets.py's fetch_asset_steps_status() -- duplicated rather than imported, deploy/ tools are each self-contained."""
    try:
        r = requests.get(
            f"{SHOT_TRACKER_URL}/classes/api/launcher/asset-steps/status",
            params={"asset_id": asset_id},
            timeout=10
        )
        r.raise_for_status()
        return r.json().get("steps", [])
    except Exception as e:
        cmds.warning(f"Could not fetch this asset's steps: {e}")
        return None


def resolve_current_asset_step():
    """
    Reads GAA_asset_id/GAA_asset_name/GAA_step off the open scene and
    resolves the step's id from Shot Tracker. Returns
    (asset_id, asset_name, step_id, step_name) or None if the scene isn't
    tagged (wasn't opened through the dashboard's Open button) or the
    tagged step can't be found anymore.
    """
    asset_id = _scene_tag("GAA_asset_id")
    asset_name = _scene_tag("GAA_asset_name")
    step_name = _scene_tag("GAA_step")

    if not asset_id or not step_name:
        cmds.warning("This scene isn't tagged with an asset/step — open it through the dashboard's Open button first.")
        return None

    steps = fetch_asset_steps(asset_id)
    if steps is None:
        return None

    step = next((s for s in steps if s.get("name") == step_name), None)
    if not step:
        cmds.warning(f"Could not find step '{step_name}' for this asset — it may have been removed from the workflow.")
        return None

    return asset_id, asset_name, step["step_id"], step_name


def submit_current_step():
    """
    POSTs a "Submitted" status update for the current scene's asset/step.
    Same endpoint/payload the web dashboard's status dropdown uses
    (update_asset_step() in films_routes.py), so it applies the identical
    crossflow cascade (e.g. unlocking a paired FB step) rather than a
    parallel Maya-only status write.
    """
    resolved = resolve_current_asset_step()
    if not resolved:
        return False
    asset_id, asset_name, step_id, step_name = resolved

    try:
        r = requests.post(
            f"{SHOT_TRACKER_URL}/films/assets/{asset_id}/steps/{step_id}/update",
            json={"status": "Submitted"},
            timeout=10
        )
        r.raise_for_status()
        result = r.json()
    except Exception as e:
        cmds.warning(f"Failed to submit: {e}")
        return False

    if not result.get("success"):
        cmds.warning(f"Submit failed: {result.get('message', 'unknown error')}")
        return False

    cmds.inViewMessage(amg=f"<hl>{asset_name}</hl> — <hl>{step_name}</hl> marked Submitted.", pos="topCenter", fade=True)
    return True


def show_ui():
    """Confirms before submitting -- cheap insurance against a stray shelf click mid-work."""
    resolved = resolve_current_asset_step()
    if not resolved:
        return
    asset_id, asset_name, step_id, step_name = resolved

    choice = cmds.confirmDialog(
        title="Submit Asset",
        message=f"Mark '{asset_name}' — {step_name} as Submitted?",
        button=["Submit", "Cancel"],
        defaultButton="Submit",
        cancelButton="Cancel",
        dismissString="Cancel"
    )
    if choice != "Submit":
        return

    submit_current_step()


if __name__ == "__main__":
    show_ui()
