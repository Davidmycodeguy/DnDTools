"""Build the starter data releases ship (installed on first run by src/models/starter_data.py): the
local market history without seller names or our own listings, plus the trained price models.

Usage (from UI/):  python scripts/export_starter_data.py [OUT_DIR]   (default: assets/starter_data)"""
import json
import os
import shutil
import sqlite3
import sys

DATA = os.path.join(os.environ["LOCALAPPDATA"], "DnDTools", "data")


def export_history(out_dir):
    source = sqlite3.connect(f"file:{os.path.join(DATA, 'market_history.sqlite')}?mode=ro", uri=True)
    target_path = os.path.join(out_dir, "market_history.sqlite")
    if os.path.exists(target_path):
        os.remove(target_path)
    target = sqlite3.connect(target_path)
    source.backup(target)  # consistent copy, WAL included
    source.close()
    target.execute("UPDATE listings SET seller = ''")      # other players' names stay private
    target.execute("DELETE FROM my_listings")              # our own listings aren't market data
    target.commit()
    target.execute("VACUUM")
    counts = {table: target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
              for (table,) in target.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    sellers = target.execute("SELECT COUNT(*) FROM listings WHERE seller != ''").fetchone()[0]
    target.close()
    return target_path, counts, sellers


def check_model(name):
    """Models are aggregate statistics; make sure no seller names ride along."""
    path = os.path.join(DATA, name)
    text = open(path, encoding="utf-8").read()
    source = sqlite3.connect(f"file:{os.path.join(DATA, 'market_history.sqlite')}?mode=ro", uri=True)
    sellers = {s for (s,) in source.execute("SELECT DISTINCT seller FROM listings WHERE length(seller) >= 4")}
    source.close()
    leaked = sorted(s for s in sellers if f'"{s}"' in text)
    return path, leaked, list(json.loads(text).keys())[:12]


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "assets", "starter_data")
    os.makedirs(out_dir, exist_ok=True)
    path, counts, sellers = export_history(out_dir)
    print(f"{path}: {os.path.getsize(path) / 1e6:.1f} MB, rows {counts}, seller names left: {sellers}")
    for name in ("worth_model.json", "market_model.json"):
        source, leaked, keys = check_model(name)
        print(f"{name}: top-level keys {keys}; seller names inside: {leaked[:5] if leaked else 'none'}")
        if not leaked:
            shutil.copy2(source, os.path.join(out_dir, name))


if __name__ == "__main__":
    main()
