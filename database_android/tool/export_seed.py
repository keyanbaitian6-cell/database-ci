"""Export the current PC database as the Android app's first-run seed."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "database" / "data" / "database.sqlite3"
TARGET = ROOT / "database_android" / "assets" / "database_seed.json"


def svg_measurement(graph: dict) -> dict | None:
    path = graph.get("path", "")
    baseline = graph.get("baseline")
    parts = re.findall(r"[ML]\s*(-?\d+(?:\.\d+)?)\s*,?\s*(-?\d+(?:\.\d+)?)", path)
    if baseline is None or len(parts) < 2:
        return None
    points = [(float(x), float(y)) for x, y in parts]
    return {
        "baseline_y": float(baseline),
        "peak_y": min(y for _, y in points),
        "trough_y": max(y for _, y in points),
        "end_y": points[-1][1],
        "method": "pc-svg-import",
    }


def main() -> None:
    connection = sqlite3.connect(SOURCE)
    try:
        raw_rows = connection.execute(
            "SELECT payload FROM days ORDER BY day, store, machine, rack"
        ).fetchall()
    finally:
        connection.close()

    rows = []
    for (raw,) in raw_rows:
        row = json.loads(raw)
        if row.get("kind_code") != 21 or row.get("store") not in {
            "nagamachiminami",
            "saiwaichou",
        }:
            continue
        if not row.get("graph_measurement") and row.get("graph"):
            row["graph_measurement"] = svg_measurement(row["graph"])
        row.pop("graph", None)
        row.pop("source_image", None)
        rows.append(row)

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps({"version": "2026-09-16-v1", "rows": rows}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"exported {len(rows)} rows to {TARGET}")


if __name__ == "__main__":
    main()
