# migrate_add_asset_step_codes.py
# Asset production OPEN-button flow: adds Modeling/Texture-Surface/Rigging
# short codes to the existing global step_codes table (name -> code,
# already used by the assignment BL/BP/P flow -- see
# launcher_routes.py:steps_status()). Since step_codes is keyed by step
# NAME rather than a specific steps.id row, this applies uniformly across
# every film/category's own copy of these step names with no per-row
# changes needed.
#
# No new lock table needed either -- step_locks already accepts an
# arbitrary entity_type string (see migrate_polymorphic_step_locks.py);
# asset production reuses it with entity_type='asset_step',
# entity_id=assets.id.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_asset_step_codes.py

import sqlite3

DB_PATH = "app/database/app.db"

STEP_CODES = {
    "Modeling": "MOD",
    "Texture/Surface": "TEX",
    "Rigging": "RIG",
}


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for step_name, code in STEP_CODES.items():
        existing = cur.execute(
            "SELECT step_code FROM step_codes WHERE step_name = ?", (step_name,)
        ).fetchone()
        if existing:
            print(f"'{step_name}' already has step_code '{existing[0]}', skipping")
            continue
        cur.execute(
            "INSERT INTO step_codes (step_name, step_code) VALUES (?, ?)",
            (step_name, code)
        )
        print(f"Inserted step_codes: {step_name} -> {code}")

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
