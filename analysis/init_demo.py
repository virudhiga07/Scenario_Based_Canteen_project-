#!/usr/bin/env python3
"""Create an isolated demonstration SQLite database from the shared SQL and JSON fixtures."""
import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def initialize(path: Path) -> None:
    # Refuse replacement: rebuilding a demo must never destroy recorded orders.
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing database: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads((ROOT / "database/seed.json").read_text(encoding="utf-8"))
    with sqlite3.connect(path) as connection:
        connection.executescript((ROOT / "database/schema.sql").read_text(encoding="utf-8"))
        connection.executemany(
            "INSERT INTO menu_items (id,name,category,description,price_paise,stock,image,active) VALUES (:id,:name,:category,:description,:price_paise,:stock,:image,:active)", data["menu"]
        )
        connection.executemany(
            "INSERT INTO orders (id,customer_name,order_type,payment_method,created_at,total_paise,is_demo) VALUES (:id,:customer_name,:order_type,:payment_method,:created_at,:total_paise,:is_demo)", data["orders"]
        )
        lines = [{**line, "order_id": order["id"]} for order in data["orders"] for line in order["items"]]
        connection.executemany(
            "INSERT INTO order_items (order_id,item_id,item_name,quantity,unit_price_paise) VALUES (:order_id,:item_id,:item_name,:quantity,:unit_price_paise)", lines
        )
        connection.execute("INSERT INTO app_meta (key,value) VALUES ('initialized','1')")
    print(f"Created {path}: {len(data['menu'])} menu items, {len(data['orders'])} sample orders, {len(lines)} sales lines")
    print("Historical sample orders are labelled is_demo=1. Stock is the supplied current balance.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data/canteen.db")
    args = parser.parse_args()
    try:
        initialize(args.db)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.error(str(error))
