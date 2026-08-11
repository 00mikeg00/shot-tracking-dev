# migrate_add_capstone_blocking_steps.py
# Inserts Blocking / FB Blocking / Blocking Plus / Polish steps between
# Layout and Animation for every capstone 3D film workflow group (identified
# by having all three of Layout, Animation, and Lighting steps in the same
# workflow_id/parent_id group -- that's the signature that distinguishes the
# capstone 3D shot pipeline from the 2D pipeline, which also has an
# "Animation" step but no Layout/Lighting).
#
# Animation itself is left untouched -- it stays the step that gates
# Lighting via films_routes.py's update_shot_status()/SHOT_FB_UNLOCKS_STEP,
# now also requiring Polish locked (see capstone_routes.shot_animation_
# approve and the Polish check added to update_shot_status()). Blocking/
# Blocking Plus/Polish are the shot-level file-versioning breakdown within
# Animation, same shape as Assignments.py's Blocking/Blocking Plus/Polish
# for individual assignments -- reusing the same step_codes rows (BL/BP/P)
# rather than inserting duplicates, since step_codes is keyed by step_name
# only, not scoped per workflow.
#
# FB Blocking is Blocking's approval pair, same relationship as FB Animation
# -> Animation: setting FB Blocking's status to "Approved" on the shots page
# kanban locks Blocking (step_locks) and lets the artist advance into
# Blocking Plus. Blocking Plus/Polish have NO FB pair -- they're self-locked
# by the artist via GAA Save, not coordinator-graded through the kanban.
#
# Safe to run more than once and safe to run after a previous partial
# version of this script already inserted Blocking/Blocking Plus/Polish
# without FB Blocking or status nodes -- each piece (steps, FB Blocking,
# nodes) is checked and backfilled independently.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_capstone_blocking_steps.py

import sqlite3

DB_PATH = "app/database/app.db"

# (name, short_code) for the production steps, in order. FB Blocking is
# inserted separately, right after Blocking, since it has no short_code /
# isn't part of the BL/BP/P file-versioned family.
NEW_STEPS = [
    ("Blocking", "BL"),
    ("Blocking Plus", "BP"),
    ("Polish", "P"),
]

# Mirrors Animation/FB Animation's node sets (see the existing steps 251/252
# in a capstone film's workflow) -- Blocking gets the full production-status
# set, Blocking Plus/Polish get a simpler self-managed set since there's no
# coordinator grading step for them, FB Blocking gets the review-queue set.
BLOCKING_NODES = [
    ("Standby", "#bcb88b", "93 21"),
    ("Ready to Start", "#ffffff", "93 72"),
    ("In Progress", "#d0fa00", "93 124"),
    ("Retake", "#ff0000", "20 360"),
    ("Needs Help", "#b271d6", "10 210"),
    ("Submitted", "#f08228", "90 290"),
    ("Approved", "#52b83d", "90 430"),
    ("CUT", "#575757", "90 520"),
]
FB_BLOCKING_NODES = [
    ("Waiting for Student", "#c5c8c9", "78 21"),
    ("In Approvals", "#e9fa00", "78 72"),
    ("Approved", "#6bd600", "80 250"),
    ("Retake", "#db1a1a", "10 130"),
    ("CUT", "#575757", "80 340"),
]
SELF_MANAGED_NODES = [
    ("Standby", "#999999", "0 0"),
    ("In Progress", "#facc15", "0 60"),
    ("Submitted", "#60a5fa", "0 120"),
    ("Done", "#4ade80", "0 180"),
    ("CUT", "#575757", "0 240"),
]


def _ensure_nodes(cur, step_id, step_name, node_set):
    existing = cur.execute("SELECT 1 FROM nodes WHERE step_id = ? LIMIT 1", (step_id,)).fetchone()
    if existing:
        return
    for name, color, position in node_set:
        cur.execute(
            "INSERT INTO nodes (name, step_id, position, color) VALUES (?, ?, ?, ?)",
            (name, step_id, position, color)
        )
    print(f"  Added {len(node_set)} status nodes to '{step_name}' (step_id={step_id})")


def _ensure_step_code(cur, name, short_code):
    existing_code = cur.execute("SELECT step_code FROM step_codes WHERE step_name = ?", (name,)).fetchone()
    if not existing_code:
        cur.execute("INSERT INTO step_codes (step_name, step_code) VALUES (?, ?)", (name, short_code))
        print(f"  Inserted step_codes: {name} -> {short_code}")


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    groups = cur.execute("""
        SELECT DISTINCT workflow_id, parent_id
        FROM steps
        WHERE workflow_id IN (SELECT workflow_id FROM steps WHERE name = 'Layout')
          AND parent_id IN (SELECT parent_id FROM steps WHERE name = 'Animation')
          AND parent_id IN (SELECT parent_id FROM steps WHERE name = 'Lighting')
          AND parent_id IS NOT NULL
    """).fetchall()

    if not groups:
        print("No capstone 3D workflow groups found (need Layout, Animation, and Lighting steps). Nothing to do.")
        conn.close()
        return

    for workflow_id, parent_id in groups:
        animation = cur.execute(
            "SELECT id, order_num FROM steps WHERE workflow_id = ? AND parent_id = ? AND name = 'Animation'",
            (workflow_id, parent_id)
        ).fetchone()
        if not animation:
            print(f"WARNING: workflow_id={workflow_id} parent_id={parent_id} matched but has no Animation step -- skipping, unexpected shape")
            continue
        _, animation_order = animation

        blocking = cur.execute(
            "SELECT id FROM steps WHERE workflow_id = ? AND parent_id = ? AND name = 'Blocking'",
            (workflow_id, parent_id)
        ).fetchone()

        if not blocking:
            insert_order = animation_order

            cur.execute("""
                UPDATE steps SET order_num = order_num + ?
                WHERE workflow_id = ? AND parent_id = ? AND order_num >= ?
            """, (len(NEW_STEPS) + 1, workflow_id, parent_id, insert_order))

            step_ids = {}
            order = insert_order
            for name, short_code in NEW_STEPS:
                cur.execute("""
                    INSERT INTO steps (name, parent_id, workflow_id, order_num, min_permission_level, short_code)
                    VALUES (?, ?, ?, ?, 1, ?)
                """, (name, parent_id, workflow_id, order, short_code))
                step_ids[name] = cur.lastrowid
                print(f"Inserted '{name}' step (id={cur.lastrowid}) at order_num={order} in workflow_id={workflow_id}/parent_id={parent_id}")
                order += 1
                if name == "Blocking":
                    cur.execute("""
                        INSERT INTO steps (name, parent_id, workflow_id, order_num, min_permission_level)
                        VALUES ('FB Blocking', ?, ?, ?, 1)
                    """, (parent_id, workflow_id, order))
                    step_ids["FB Blocking"] = cur.lastrowid
                    print(f"Inserted 'FB Blocking' step (id={cur.lastrowid}) at order_num={order} in workflow_id={workflow_id}/parent_id={parent_id}")
                    order += 1

            blocking_id = step_ids["Blocking"]
            fb_blocking_id = step_ids["FB Blocking"]
            bp_id = step_ids["Blocking Plus"]
            polish_id = step_ids["Polish"]
        else:
            blocking_id = blocking[0]
            fb_blocking = cur.execute(
                "SELECT id FROM steps WHERE workflow_id = ? AND parent_id = ? AND name = 'FB Blocking'",
                (workflow_id, parent_id)
            ).fetchone()
            if fb_blocking:
                fb_blocking_id = fb_blocking[0]
            else:
                blocking_order = cur.execute("SELECT order_num FROM steps WHERE id = ?", (blocking_id,)).fetchone()[0]
                cur.execute("""
                    UPDATE steps SET order_num = order_num + 1
                    WHERE workflow_id = ? AND parent_id = ? AND order_num > ?
                """, (workflow_id, parent_id, blocking_order))
                cur.execute("""
                    INSERT INTO steps (name, parent_id, workflow_id, order_num, min_permission_level)
                    VALUES ('FB Blocking', ?, ?, ?, 1)
                """, (parent_id, workflow_id, blocking_order + 1))
                fb_blocking_id = cur.lastrowid
                print(f"Backfilled 'FB Blocking' step (id={fb_blocking_id}) at order_num={blocking_order + 1} in workflow_id={workflow_id}/parent_id={parent_id}")

            bp_row = cur.execute(
                "SELECT id FROM steps WHERE workflow_id = ? AND parent_id = ? AND name = 'Blocking Plus'",
                (workflow_id, parent_id)
            ).fetchone()
            polish_row = cur.execute(
                "SELECT id FROM steps WHERE workflow_id = ? AND parent_id = ? AND name = 'Polish'",
                (workflow_id, parent_id)
            ).fetchone()
            bp_id = bp_row[0] if bp_row else None
            polish_id = polish_row[0] if polish_row else None
            print(f"workflow_id={workflow_id} parent_id={parent_id} already has a Blocking step (id={blocking_id}), checking for missing pieces")

        for name, short_code in NEW_STEPS:
            _ensure_step_code(cur, name, short_code)

        _ensure_nodes(cur, blocking_id, "Blocking", BLOCKING_NODES)
        _ensure_nodes(cur, fb_blocking_id, "FB Blocking", FB_BLOCKING_NODES)
        if bp_id:
            _ensure_nodes(cur, bp_id, "Blocking Plus", SELF_MANAGED_NODES)
        if polish_id:
            _ensure_nodes(cur, polish_id, "Polish", SELF_MANAGED_NODES)

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
