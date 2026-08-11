# migrate_add_proxy_step.py
# Adds a "Proxy" step between Design and Modeling for every Character/Rigs-
# shaped asset workflow (identified by having both a Modeling and a
# Rigging step in the same workflow_id/parent_id group -- that's the
# signature that distinguishes Character/Rigs from Sets/BGs/Props, which
# share Design/Modeling/Texture-Surface but never have Rigging).
#
# Proxy is deliberately NOT gated like Modeling/Texture-Surface/Rigging --
# no FB Proxy pair, no step_locks entry, no unlock hook. It's tracked
# status only; Modeling can start whenever regardless of Proxy's status.
# See step_codes: 'Proxy' -> 'PROXY', used by Assets.py/CapstoneLayout.py
# for its own independent, non-gated file lineage (find_latest_version_for_step()
# with step_code='PROXY').
#
# For every workflow group found, this:
#   1. Inserts the Proxy step at order_num = Design's order_num + 1
#   2. Shifts every step at or after that order_num up by 1
#   3. Clones a small Proxy-appropriate node set (Standby/In Progress/
#      Submitted/Done/Cut) onto the new step -- Design's own node names
#      (Rough/Turnarounds/Final Design) are Design-specific vocabulary and
#      don't fit Proxy, so this is a fresh, simple status set rather than a
#      literal clone.
#   4. Backfills an asset_step_assignments row (default node/status) for
#      every existing Character/Rigs asset in that workflow, so Proxy shows
#      up immediately for assets that already exist, not just new ones.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_proxy_step.py

import sqlite3

DB_PATH = "app/database/app.db"

PROXY_NODES = [
    ("Standby", "#999999", "0 0"),
    ("In Progress", "#facc15", "0 60"),
    ("Submitted", "#60a5fa", "0 120"),
    ("Done", "#4ade80", "0 180"),
    ("Cut", "#575757", "0 240"),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    groups = cur.execute("""
        SELECT DISTINCT workflow_id, parent_id
        FROM steps
        WHERE workflow_id IN (SELECT workflow_id FROM steps WHERE name = 'Rigging')
          AND parent_id IN (SELECT parent_id FROM steps WHERE name = 'Modeling')
          AND parent_id IS NOT NULL
    """).fetchall()

    if not groups:
        print("No Character/Rigs-shaped workflow groups found (need both Modeling and Rigging steps). Nothing to do.")
        conn.close()
        return

    for workflow_id, parent_id in groups:
        design = cur.execute(
            "SELECT id, order_num FROM steps WHERE workflow_id = ? AND parent_id = ? AND name = 'Design'",
            (workflow_id, parent_id)
        ).fetchone()
        if not design:
            print(f"WARNING: workflow_id={workflow_id} parent_id={parent_id} has Modeling/Rigging but no Design step -- skipping, unexpected shape")
            continue
        design_id, design_order = design

        existing_proxy = cur.execute(
            "SELECT id FROM steps WHERE workflow_id = ? AND parent_id = ? AND name = 'Proxy'",
            (workflow_id, parent_id)
        ).fetchone()
        if existing_proxy:
            print(f"workflow_id={workflow_id} parent_id={parent_id} already has a Proxy step (id={existing_proxy[0]}), skipping")
            continue

        proxy_order = design_order + 1

        cur.execute("""
            UPDATE steps SET order_num = order_num + 1
            WHERE workflow_id = ? AND parent_id = ? AND order_num >= ?
        """, (workflow_id, parent_id, proxy_order))

        cur.execute("""
            INSERT INTO steps (name, parent_id, workflow_id, order_num, min_permission_level, short_code)
            VALUES ('Proxy', ?, ?, ?, 1, NULL)
        """, (parent_id, workflow_id, proxy_order))
        proxy_step_id = cur.lastrowid
        print(f"Inserted 'Proxy' step (id={proxy_step_id}) at order_num={proxy_order} in workflow_id={workflow_id}/parent_id={parent_id}")

        standby_node_id = None
        for name, color, position in PROXY_NODES:
            cur.execute(
                "INSERT INTO nodes (name, step_id, position, color) VALUES (?, ?, ?, ?)",
                (name, proxy_step_id, position, color)
            )
            if name == "Standby":
                standby_node_id = cur.lastrowid
        print(f"  Added {len(PROXY_NODES)} status nodes to Proxy step {proxy_step_id}")

        asset_ids = cur.execute("""
            SELECT DISTINCT asa.asset_id
            FROM asset_step_assignments asa
            JOIN assets a ON a.id = asa.asset_id
            WHERE a.category = 'Character/Rigs'
              AND asa.step_id IN (SELECT id FROM steps WHERE workflow_id = ? AND parent_id = ?)
        """, (workflow_id, parent_id)).fetchall()

        backfilled = 0
        for (asset_id,) in asset_ids:
            already = cur.execute(
                "SELECT 1 FROM asset_step_assignments WHERE asset_id = ? AND step_id = ?",
                (asset_id, proxy_step_id)
            ).fetchone()
            if already:
                continue
            cur.execute("""
                INSERT INTO asset_step_assignments (asset_id, step_id, node_id, status)
                VALUES (?, ?, ?, 'Standby')
            """, (asset_id, proxy_step_id, standby_node_id))
            backfilled += 1
        print(f"  Backfilled Proxy assignment for {backfilled} existing Character/Rigs asset(s)")

        existing_code = cur.execute("SELECT step_code FROM step_codes WHERE step_name = 'Proxy'").fetchone()
        if not existing_code:
            cur.execute("INSERT INTO step_codes (step_name, step_code) VALUES ('Proxy', 'PROXY')")
            print("  Inserted step_codes: Proxy -> PROXY")

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
