# launcher.py
# UC GAA Shot Tracker — Maya Launcher Bridge
# Receives shottracker:// URI from Windows registry and opens Maya.
# Writes session context for the GAA shelf to read.
#
# URI format: shottracker://open?class_id=13&login_name=bariann&assignment_id=84

import sys
import os
import re
import json
import datetime
import subprocess
import urllib.parse
import requests

# ── Config ────────────────────────────────────────────────────
# Override locally with a SHOT_TRACKER_URL environment variable pointed at your
# dev server — the committed default must stay the intranet address since this
# file is copied verbatim to lab machines by the installer.
SHOT_TRACKER_URL  = os.environ.get("SHOT_TRACKER_URL", "http://10.23.20.210:8000")
MAYA_EXE          = r"C:\Program Files\Autodesk\Maya2026\bin\maya.exe"
LOG_PATH          = r"C:\Cincy\logs\launcher_log.txt"
SESSIONS_PATH     = r"C:\Cincy\sessions"

# ── Logging ───────────────────────────────────────────────────
def log(message):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a") as f:
        f.write(f"[{timestamp}] {message}\n")
    print(f"[{timestamp}] {message}")

# ── URI Parsing ───────────────────────────────────────────────
def parse_uri(uri):
    """
    Parse shottracker://open?class_id=13&login_name=bariann&assignment_id=84
    Returns dict of params or None on failure.
    """
    try:
        uri = uri.replace("shottracker://", "http://localhost/")
        parsed = urllib.parse.urlparse(uri)
        params = urllib.parse.parse_qs(parsed.query)
        return {k: v[0] for k, v in params.items()}
    except Exception as e:
        log(f"ERROR parsing URI: {e}")
        return None

# ── Shot Tracker API ──────────────────────────────────────────
def get_class_context(class_id, login_name):
    """
    Calls Shot Tracker API and returns full class context dict
    containing user info and all assignments with rig configs.
    """
    try:
        url = f"{SHOT_TRACKER_URL}/classes/api/launcher/class-context"
        r = requests.get(url, params={
            "class_id":   class_id,
            "login_name": login_name
        }, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"ERROR fetching class context: {e}")
        return None


def get_scene_layout_context(scene_id, login_name):
    """
    Calls Shot Tracker's capstone API and returns the scene-Layout context
    dict (film/scene identity, Sets+Character/Rigs assets to reference,
    current lock state) for the Maya-side capstone flow.
    """
    try:
        url = f"{SHOT_TRACKER_URL}/classes/api/launcher/capstone/scene-layout/context"
        r = requests.get(url, params={
            "scene_id":   scene_id,
            "login_name": login_name
        }, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"ERROR fetching scene layout context: {e}")
        return None


def get_shot_layout_context(shot_id, login_name):
    """
    Calls Shot Tracker's capstone API and returns the shot-Layout context
    dict (film/scene/shot identity, whether scene Layout is done yet,
    current lock state) for the Maya-side capstone flow.
    """
    try:
        url = f"{SHOT_TRACKER_URL}/classes/api/launcher/capstone/shot-layout/context"
        r = requests.get(url, params={
            "shot_id":    shot_id,
            "login_name": login_name
        }, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"ERROR fetching shot layout context: {e}")
        return None


def get_shot_animation_context(shot_id, login_name):
    """
    Calls Shot Tracker's capstone API and returns the shot-Animation
    context dict (film/scene/shot identity, whether Layout is approved
    yet, current lock state) for the Maya-side capstone flow.
    """
    try:
        url = f"{SHOT_TRACKER_URL}/classes/api/launcher/capstone/shot-animation/context"
        r = requests.get(url, params={
            "shot_id":    shot_id,
            "login_name": login_name
        }, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"ERROR fetching shot animation context: {e}")
        return None


def get_shot_lighting_context(shot_id, login_name):
    """
    Calls Shot Tracker's capstone API and returns the shot-Lighting
    context dict (film/scene/shot identity, whether Animation is approved
    yet, current lock state, Light Rigs assets to reference) for the
    Maya-side capstone flow.
    """
    try:
        url = f"{SHOT_TRACKER_URL}/classes/api/launcher/capstone/shot-lighting/context"
        r = requests.get(url, params={
            "shot_id":    shot_id,
            "login_name": login_name
        }, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"ERROR fetching shot lighting context: {e}")
        return None

# ── Session File ──────────────────────────────────────────────
def write_session_context(context):
    r"""
    Writes the class context JSON to C:\Cincy\sessions\{login_name}_context.json
    Keyed by login_name so two students sharing a machine never collide.
    """
    login_name    = context["user"]["login_name"]
    session_file  = os.path.join(SESSIONS_PATH, f"{login_name}_context.json")

    os.makedirs(SESSIONS_PATH, exist_ok=True)

    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2)

    log(f"Session context written: {session_file}")
    return session_file


def write_scene_layout_session(context):
    r"""
    Writes the scene-Layout context JSON to
    C:\Cincy\sessions\{login_name}_scene_layout_context.json -- a distinct
    filename from write_session_context()'s {login_name}_context.json so a
    student's assignment session and capstone scene-Layout session never
    clobber each other on a shared lab machine.
    """
    login_name   = context["user"]["login_name"]
    session_file = os.path.join(SESSIONS_PATH, f"{login_name}_scene_layout_context.json")

    os.makedirs(SESSIONS_PATH, exist_ok=True)

    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2)

    log(f"Scene layout session context written: {session_file}")
    return session_file


def write_shot_layout_session(context):
    r"""
    Writes the shot-Layout context JSON to
    C:\Cincy\sessions\{login_name}_shot_layout_context.json -- distinct
    from both the assignment and scene-Layout session files.
    """
    login_name   = context["user"]["login_name"]
    session_file = os.path.join(SESSIONS_PATH, f"{login_name}_shot_layout_context.json")

    os.makedirs(SESSIONS_PATH, exist_ok=True)

    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2)

    log(f"Shot layout session context written: {session_file}")
    return session_file


def write_shot_animation_session(context):
    r"""
    Writes the shot-Animation context JSON to
    C:\Cincy\sessions\{login_name}_shot_animation_context.json.
    """
    login_name   = context["user"]["login_name"]
    session_file = os.path.join(SESSIONS_PATH, f"{login_name}_shot_animation_context.json")

    os.makedirs(SESSIONS_PATH, exist_ok=True)

    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2)

    log(f"Shot animation session context written: {session_file}")
    return session_file


def write_shot_lighting_session(context):
    r"""
    Writes the shot-Lighting context JSON to
    C:\Cincy\sessions\{login_name}_shot_lighting_context.json.
    """
    login_name   = context["user"]["login_name"]
    session_file = os.path.join(SESSIONS_PATH, f"{login_name}_shot_lighting_context.json")

    os.makedirs(SESSIONS_PATH, exist_ok=True)

    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2)

    log(f"Shot lighting session context written: {session_file}")
    return session_file

# ── Maya Launch ───────────────────────────────────────────────
_SAFE_LOGIN_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")

def launch_maya(login_name, individual_assignment_id=None):
    """
    Launches Maya and, via the -command startup flag, immediately runs
    Assignments.py — it opens the student's existing scene if one exists,
    or creates it from config if this is their first time. No shelf
    button, no manual step.
    """
    log(f"Launching Maya: {MAYA_EXE}")

    if not _SAFE_LOGIN_NAME.match(login_name or ""):
        log(f"ERROR: login_name '{login_name}' contains unsafe characters; launching Maya clean instead")
        subprocess.Popen([MAYA_EXE])
        return

    try:
        assignment_arg = str(int(individual_assignment_id)) if individual_assignment_id is not None else "None"
    except (TypeError, ValueError):
        log(f"WARNING: individual_assignment_id '{individual_assignment_id}' is not a valid integer; ignoring")
        assignment_arg = "None"

    # Single-quoted Python string literals nested inside a double-quoted MEL
    # string — login_name is regex-validated above so it can't contain a
    # quote character and break out of either layer.
    python_code = (
        "import sys; "
        "sys.path.insert(0, 'C:/Cincy/scripts'); "
        "import Assignments; "
        f"Assignments.run(login_name='{login_name}', individual_assignment_id={assignment_arg})"
    )
    # Deferred rather than run inline — Maya's -command content executes
    # before the UI (panels, shelves) has finished constructing. Running
    # Assignments.py that early was already caught causing a "modelPanel4
    # not found" error from userSetup.mel; it's the same likely cause of
    # the GAA shelf loading empty/getting blanked on exit. evalDeferred
    # queues this to run once Maya's idle event loop picks it up, after
    # the UI is actually built — same idiom userSetup.mel already uses
    # for plugin autoloading.
    mel_command = f'evalDeferred("python(\\"{python_code}\\")")'

    subprocess.Popen([MAYA_EXE, "-command", mel_command])


def launch_maya_scene_layout(login_name, scene_id):
    """
    Launches Maya and runs CapstoneLayout.run() for one scene's Layout,
    same evalDeferred idiom as launch_maya() and for the same reason (Maya's
    -command content runs before the UI has finished constructing).
    """
    log(f"Launching Maya (scene Layout): {MAYA_EXE}")

    if not _SAFE_LOGIN_NAME.match(login_name or ""):
        log(f"ERROR: login_name '{login_name}' contains unsafe characters; launching Maya clean instead")
        subprocess.Popen([MAYA_EXE])
        return

    try:
        scene_id_arg = str(int(scene_id))
    except (TypeError, ValueError):
        log(f"ERROR: scene_id '{scene_id}' is not a valid integer; launching Maya clean instead")
        subprocess.Popen([MAYA_EXE])
        return

    python_code = (
        "import sys; "
        "sys.path.insert(0, 'C:/Cincy/scripts'); "
        "import CapstoneLayout; "
        f"CapstoneLayout.run(login_name='{login_name}', scene_id={scene_id_arg})"
    )
    mel_command = f'evalDeferred("python(\\"{python_code}\\")")'

    subprocess.Popen([MAYA_EXE, "-command", mel_command])


def launch_maya_shot_layout(login_name, shot_id):
    """
    Launches Maya and runs CapstoneLayout.run_shot() for one shot's
    Layout, same evalDeferred idiom as the other launch_maya_* helpers.
    """
    log(f"Launching Maya (shot Layout): {MAYA_EXE}")

    if not _SAFE_LOGIN_NAME.match(login_name or ""):
        log(f"ERROR: login_name '{login_name}' contains unsafe characters; launching Maya clean instead")
        subprocess.Popen([MAYA_EXE])
        return

    try:
        shot_id_arg = str(int(shot_id))
    except (TypeError, ValueError):
        log(f"ERROR: shot_id '{shot_id}' is not a valid integer; launching Maya clean instead")
        subprocess.Popen([MAYA_EXE])
        return

    python_code = (
        "import sys; "
        "sys.path.insert(0, 'C:/Cincy/scripts'); "
        "import CapstoneLayout; "
        f"CapstoneLayout.run_shot(login_name='{login_name}', shot_id={shot_id_arg})"
    )
    mel_command = f'evalDeferred("python(\\"{python_code}\\")")'

    subprocess.Popen([MAYA_EXE, "-command", mel_command])


def launch_maya_shot_animation(login_name, shot_id):
    """
    Launches Maya and runs CapstoneAnimation.run_shot() for one shot's
    Animation, same evalDeferred idiom as the other launch_maya_* helpers.
    """
    log(f"Launching Maya (shot Animation): {MAYA_EXE}")

    if not _SAFE_LOGIN_NAME.match(login_name or ""):
        log(f"ERROR: login_name '{login_name}' contains unsafe characters; launching Maya clean instead")
        subprocess.Popen([MAYA_EXE])
        return

    try:
        shot_id_arg = str(int(shot_id))
    except (TypeError, ValueError):
        log(f"ERROR: shot_id '{shot_id}' is not a valid integer; launching Maya clean instead")
        subprocess.Popen([MAYA_EXE])
        return

    python_code = (
        "import sys; "
        "sys.path.insert(0, 'C:/Cincy/scripts'); "
        "import CapstoneAnimation; "
        f"CapstoneAnimation.run_shot(login_name='{login_name}', shot_id={shot_id_arg})"
    )
    mel_command = f'evalDeferred("python(\\"{python_code}\\")")'

    subprocess.Popen([MAYA_EXE, "-command", mel_command])


def launch_maya_shot_lighting(login_name, shot_id):
    """
    Launches Maya and runs CapstoneLighting.run_shot() for one shot's
    Lighting, same evalDeferred idiom as the other launch_maya_* helpers.
    """
    log(f"Launching Maya (shot Lighting): {MAYA_EXE}")

    if not _SAFE_LOGIN_NAME.match(login_name or ""):
        log(f"ERROR: login_name '{login_name}' contains unsafe characters; launching Maya clean instead")
        subprocess.Popen([MAYA_EXE])
        return

    try:
        shot_id_arg = str(int(shot_id))
    except (TypeError, ValueError):
        log(f"ERROR: shot_id '{shot_id}' is not a valid integer; launching Maya clean instead")
        subprocess.Popen([MAYA_EXE])
        return

    python_code = (
        "import sys; "
        "sys.path.insert(0, 'C:/Cincy/scripts'); "
        "import CapstoneLighting; "
        f"CapstoneLighting.run_shot(login_name='{login_name}', shot_id={shot_id_arg})"
    )
    mel_command = f'evalDeferred("python(\\"{python_code}\\")")'

    subprocess.Popen([MAYA_EXE, "-command", mel_command])

# ── Main ──────────────────────────────────────────────────────
def main():
    log("=" * 50)
    log("Shot Tracker Launcher started")

    if len(sys.argv) < 2:
        log("ERROR: No URI argument received")
        sys.exit(1)

    uri = sys.argv[1]
    log(f"URI received: {uri}")

    # Parse URI
    params = parse_uri(uri)
    if not params:
        log("ERROR: Could not parse URI")
        sys.exit(1)

    # action defaults to the original assignment flow so every existing
    # shottracker://open?class_id=...&login_name=... URI already deployed
    # keeps working unchanged.
    action = params.get("action", "assignment")

    if action == "scene_layout":
        _main_scene_layout(params)
        return

    if action == "shot_layout":
        _main_shot_layout(params)
        return

    if action == "shot_animation":
        _main_shot_animation(params)
        return

    if action == "shot_lighting":
        _main_shot_lighting(params)
        return

    class_id      = params.get("class_id")
    login_name    = params.get("login_name")
    assignment_id = params.get("assignment_id")

    if not class_id or not login_name:
        log("ERROR: Missing class_id or login_name in URI")
        sys.exit(1)

    log(f"class_id={class_id} login_name={login_name} assignment_id={assignment_id}")

    # Get full class context from Shot Tracker
    context = get_class_context(class_id, login_name)
    if not context:
        log("ERROR: Could not get class context from Shot Tracker")
        sys.exit(1)

    log(f"Context received for user: {context['user']['display_name']}")
    log(f"Class: {context['class']['name']}")
    log(f"Assignments: {len(context['assignments'])}")

    # Tag which assignment the student actually clicked OPEN on, so the
    # shelf can jump straight to it instead of showing a picker.
    if assignment_id:
        active = next(
            (a for a in context["assignments"] if str(a["assignment_id"]) == str(assignment_id)),
            None
        )
        if active:
            context["active_assignment_id"] = active["individual_assignment_id"]
            log(f"Active assignment resolved: {active['name']} (individual_assignment_id={active['individual_assignment_id']})")
        else:
            log(f"WARNING: assignment_id={assignment_id} not found in class context; shelf will fall back to picker")

    # Write session file for the shelf to read
    session_file = write_session_context(context)
    log(f"Session ready: {session_file}")

    # Launch Maya — Assignments.py runs automatically via -command,
    # opening this student's existing scene or creating it from config.
    launch_maya(context["user"]["login_name"], context.get("active_assignment_id"))
    log("Maya launch initiated")


def _main_scene_layout(params):
    """
    shottracker://open?action=scene_layout&scene_id=9&login_name=bariann
    """
    scene_id   = params.get("scene_id")
    login_name = params.get("login_name")

    if not scene_id or not login_name:
        log("ERROR: Missing scene_id or login_name in URI")
        sys.exit(1)

    log(f"action=scene_layout scene_id={scene_id} login_name={login_name}")

    context = get_scene_layout_context(scene_id, login_name)
    if not context:
        log("ERROR: Could not get scene layout context from Shot Tracker")
        sys.exit(1)

    log(f"Context received for user: {context['user']['display_name']}")
    log(f"Film: {context['film_name']} Scene: {context['scene_number']}")

    session_file = write_scene_layout_session(context)
    log(f"Scene layout session ready: {session_file}")

    launch_maya_scene_layout(context["user"]["login_name"], context["scene_id"])
    log("Maya launch initiated (scene layout)")


def _main_shot_layout(params):
    """
    shottracker://open?action=shot_layout&shot_id=373&login_name=bariann
    """
    shot_id    = params.get("shot_id")
    login_name = params.get("login_name")

    if not shot_id or not login_name:
        log("ERROR: Missing shot_id or login_name in URI")
        sys.exit(1)

    log(f"action=shot_layout shot_id={shot_id} login_name={login_name}")

    context = get_shot_layout_context(shot_id, login_name)
    if not context:
        log("ERROR: Could not get shot layout context from Shot Tracker")
        sys.exit(1)

    log(f"Context received for user: {context['user']['display_name']}")
    log(f"Film: {context['film_name']} Scene: {context['scene_number']} Shot: {context['shot_number']}")

    session_file = write_shot_layout_session(context)
    log(f"Shot layout session ready: {session_file}")

    launch_maya_shot_layout(context["user"]["login_name"], context["shot_id"])
    log("Maya launch initiated (shot layout)")


def _main_shot_animation(params):
    """
    shottracker://open?action=shot_animation&shot_id=373&login_name=bariann
    """
    shot_id    = params.get("shot_id")
    login_name = params.get("login_name")

    if not shot_id or not login_name:
        log("ERROR: Missing shot_id or login_name in URI")
        sys.exit(1)

    log(f"action=shot_animation shot_id={shot_id} login_name={login_name}")

    context = get_shot_animation_context(shot_id, login_name)
    if not context:
        log("ERROR: Could not get shot animation context from Shot Tracker")
        sys.exit(1)

    log(f"Context received for user: {context['user']['display_name']}")
    log(f"Film: {context['film_name']} Scene: {context['scene_number']} Shot: {context['shot_number']}")

    session_file = write_shot_animation_session(context)
    log(f"Shot animation session ready: {session_file}")

    launch_maya_shot_animation(context["user"]["login_name"], context["shot_id"])
    log("Maya launch initiated (shot animation)")


def _main_shot_lighting(params):
    """
    shottracker://open?action=shot_lighting&shot_id=373&login_name=bariann
    """
    shot_id    = params.get("shot_id")
    login_name = params.get("login_name")

    if not shot_id or not login_name:
        log("ERROR: Missing shot_id or login_name in URI")
        sys.exit(1)

    log(f"action=shot_lighting shot_id={shot_id} login_name={login_name}")

    context = get_shot_lighting_context(shot_id, login_name)
    if not context:
        log("ERROR: Could not get shot lighting context from Shot Tracker")
        sys.exit(1)

    log(f"Context received for user: {context['user']['display_name']}")
    log(f"Film: {context['film_name']} Scene: {context['scene_number']} Shot: {context['shot_number']}")

    session_file = write_shot_lighting_session(context)
    log(f"Shot lighting session ready: {session_file}")

    launch_maya_shot_lighting(context["user"]["login_name"], context["shot_id"])
    log("Maya launch initiated (shot lighting)")


if __name__ == "__main__":
    main()