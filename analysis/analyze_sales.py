#!/usr/bin/env python3
"""Retrieve, validate, aggregate and chart canteen sales. Never modifies source data."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

TIMEZONE = "Asia/Kolkata"
REQUIRED = ["order_id", "created_at", "item_id", "item_name", "quantity", "unit_price_paise"]
COLUMNS = REQUIRED + ["line_total_paise", "customer_name", "order_type", "payment_method", "is_demo"]
SALES_SQL = """
SELECT o.id AS order_id, o.created_at, o.customer_name, o.order_type,
       o.payment_method, o.is_demo, oi.item_id, oi.item_name,
       oi.quantity, oi.unit_price_paise,
       oi.quantity * oi.unit_price_paise AS line_total_paise
FROM orders AS o JOIN order_items AS oi ON oi.order_id = o.id
ORDER BY o.created_at, o.id, oi.item_id
"""


def retrieve_database(path: Path, account_id: str | None = None) -> pd.DataFrame:
    """Read the Java app's SQLite database in read-only mode, including historical prices."""
    resolved = path.resolve(strict=True)
    with sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True) as connection:
        has_accounts = any(row[1] == "account_id" for row in connection.execute("PRAGMA table_info(orders)"))
        if account_id is not None and not has_accounts:
            raise ValueError("This legacy database has no account_id column; account filtering is unavailable.")
        query = SALES_SQL
        if has_accounts:
            query = query.replace("SELECT o.id AS order_id,", "SELECT o.account_id, o.id AS order_id,")
        parameters = []
        if account_id is not None:
            query = query.replace("ORDER BY o.created_at", "WHERE o.account_id = ?\nORDER BY o.created_at")
            parameters.append(account_id)
        return pd.read_sql_query(query, connection, params=parameters)


def preprocess(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    missing = sorted(set(REQUIRED) - set(raw.columns))
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(missing))
    frame = raw.copy().reset_index(drop=True)
    for column in ("customer_name", "order_type", "payment_method"):
        if column not in frame:
            frame[column] = ""
    if "is_demo" not in frame:
        frame["is_demo"] = 0
    reasons = pd.Series("", index=frame.index, dtype="string")

    def reject(mask: pd.Series, reason: str) -> None:
        nonlocal reasons
        mask = mask.fillna(True)
        reasons.loc[mask] = reasons.loc[mask].map(lambda previous: previous + "; " + reason if previous else reason)

    for column in ("order_id", "item_name"):
        frame[column] = frame[column].astype("string").str.strip()
        reject(frame[column].isna() | frame[column].eq(""), "missing " + column)
    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce", utc=True, format="mixed")
    reject(frame["created_at"].isna(), "invalid timestamp")
    for column in ("item_id", "quantity", "unit_price_paise", "is_demo"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        invalid = frame[column].isna() | frame[column].mod(1).ne(0)
        invalid |= ~frame[column].between(0 if column == "is_demo" else 1, 1 if column == "is_demo" else 2**31 - 1)
        reject(invalid, "invalid " + column)
    expected_total = frame["quantity"] * frame["unit_price_paise"]
    if "line_total_paise" in frame:
        frame["line_total_paise"] = pd.to_numeric(frame["line_total_paise"], errors="coerce")
        reject(frame["line_total_paise"].isna() | frame["line_total_paise"].ne(expected_total), "line total mismatch")
    else:
        frame["line_total_paise"] = expected_total

    valid = frame.loc[reasons.eq("")].copy()
    key = ["order_id", "item_id"]
    # An order may contain several different items. Never deduplicate order_id alone.
    comparison = [column for column in COLUMNS if column in valid]
    repeated_exact = valid.duplicated(subset=comparison, keep="first")
    exact_duplicates = int(repeated_exact.sum())
    valid = valid.loc[~repeated_exact].copy()
    conflicting = valid.duplicated(subset=key, keep=False)
    conflict_indexes = valid.index[conflicting]
    reasons.loc[conflict_indexes] = "conflicting duplicate order/item"
    valid = valid.loc[~conflicting].copy()
    for column in ("item_id", "quantity", "unit_price_paise", "line_total_paise", "is_demo"):
        valid[column] = valid[column].astype("int64")
    valid["sale_date"] = valid["created_at"].dt.tz_convert(TIMEZONE).dt.strftime("%Y-%m-%d")
    valid["revenue_inr"] = valid["line_total_paise"] / 100
    valid = valid.sort_values(["created_at", "order_id", "item_id"]).reset_index(drop=True)
    rejected = raw.reset_index(drop=True).loc[reasons.ne("")].copy()
    rejected["rejection_reason"] = reasons.loc[reasons.ne("")]
    report = {
        "input_rows": len(raw), "valid_rows": len(valid),
        "exact_duplicates_removed": exact_duplicates, "rejected_rows": len(rejected),
        "reporting_timezone": TIMEZONE,
    }
    return valid, rejected, report


def aggregate(clean: pd.DataFrame, start: str | None = None, end: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    if clean.empty:
        return pd.DataFrame(columns=["item_id", "item_name", "units", "revenue_inr"]), pd.DataFrame(columns=["sale_date", "revenue_inr", "orders", "units"])
    items = clean.groupby("item_id", as_index=False).agg(item_name=("item_name", "last"), units=("quantity", "sum"), revenue_inr=("revenue_inr", "sum"))
    items = items.sort_values(["units", "revenue_inr"], ascending=False)
    daily = clean.groupby("sale_date").agg(revenue_inr=("revenue_inr", "sum"), orders=("order_id", "nunique"), units=("quantity", "sum"))
    dates = pd.date_range(start or daily.index.min(), end or daily.index.max()).strftime("%Y-%m-%d")
    daily = daily.reindex(dates, fill_value=0).rename_axis("sale_date").reset_index()
    return items, daily


def draw_charts(items: pd.DataFrame, daily: pd.DataFrame, output: Path) -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False, "figure.facecolor": "#f6f7f2", "axes.facecolor": "#f6f7f2", "axes.titleweight": "bold", "font.size": 10})
    for filename, title, metric, label in [
        ("item_sales.png", "Item-wise sales revenue", "revenue_inr", "Revenue (INR)"),
        ("popular_items.png", "Most popular food items", "units", "Units sold"),
    ]:
        fig, ax = plt.subplots(figsize=(10, 6), constrained_layout=True)
        if items.empty:
            ax.text(.5, .5, "No sales in the selected period", ha="center", va="center", transform=ax.transAxes)
        else:
            top = items.nlargest(10, metric).sort_values(metric)
            bars = ax.barh(top["item_name"], top[metric], color="#146557", height=.65)
            ax.bar_label(bars, fmt="{:,.0f}" if metric == "units" else "{:,.2f}", padding=5)
            ax.set_xlim(right=max(top[metric]) * 1.2)
        ax.set(title=title, xlabel=label)
        ax.grid(axis="x", alpha=.15)
        ax.set_axisbelow(True)
        fig.savefig(output / filename, dpi=180)
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    if daily.empty:
        ax.text(.5, .5, "No sales in the selected period", ha="center", va="center", transform=ax.transAxes)
    else:
        dates = pd.to_datetime(daily["sale_date"])
        ax.plot(dates, daily["revenue_inr"], color="#146557", marker="o", linewidth=2)
        ax.fill_between(dates, daily["revenue_inr"], color="#146557", alpha=.1)
        fig.autofmt_xdate()
    ax.set(title="Daily revenue · Asia/Kolkata", xlabel="Date", ylabel="Revenue (INR)", ylim=(0, None))
    ax.grid(axis="y", alpha=.15)
    fig.savefig(output / "daily_revenue.png", dpi=180)
    plt.close(fig)


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--db", type=Path, help="SQLite database produced by the Java app")
    source.add_argument("--csv", type=Path, help="Sales line CSV exported from the web app")
    parser.add_argument("--out", type=Path, default=Path("analysis/output"))
    parser.add_argument("--start", help="Inclusive India reporting date: YYYY-MM-DD")
    parser.add_argument("--end", help="Inclusive India reporting date: YYYY-MM-DD")
    parser.add_argument("--account-id", help="Filter one account ID in SQLite or a CSV containing account_id; not an authentication mechanism")
    parser.add_argument("--exclude-demo", action="store_true", help="Exclude labelled initial sample records")
    args = parser.parse_args(argv)
    for boundary in (args.start, args.end):
        if boundary:
            try:
                from datetime import date
                if date.fromisoformat(boundary).isoformat() != boundary:
                    raise ValueError()
            except ValueError:
                parser.error("Date boundaries must use YYYY-MM-DD")
    if args.start and args.end and args.start > args.end:
        parser.error("--start must not be after --end")
    try:
        raw = retrieve_database(args.db, args.account_id) if args.db else pd.read_csv(args.csv, dtype={"order_id": "string", "item_name": "string", "account_id": "string"})
        if args.csv and args.account_id is not None:
            if "account_id" not in raw:
                raise ValueError("CSV account filtering requires an account_id column. The web app already exports only the signed-in account; omit --account-id for that export.")
            raw = raw.loc[raw["account_id"].astype("string").eq(args.account_id)].copy()
        clean, rejected, report = preprocess(raw)
    except (OSError, sqlite3.Error, pd.errors.DatabaseError, pd.errors.ParserError, ValueError) as error:
        parser.error(str(error))
    if args.exclude_demo:
        clean = clean.loc[clean["is_demo"].eq(0)]
    if args.start:
        clean = clean.loc[clean["sale_date"].ge(args.start)]
    if args.end:
        clean = clean.loc[clean["sale_date"].le(args.end)]
    items, daily = aggregate(clean, args.start, args.end)
    args.out.mkdir(parents=True, exist_ok=True)
    clean.to_csv(args.out / "cleaned_sales.csv", index=False)
    rejected.to_csv(args.out / "rejected_rows.csv", index=False)
    items.to_csv(args.out / "item_sales.csv", index=False)
    daily.to_csv(args.out / "daily_revenue.csv", index=False)
    summary = {
        "source": str(args.db or args.csv), "preprocessing": report,
        "selection": {"start": args.start, "end": args.end, "exclude_demo": args.exclude_demo, "account_id": args.account_id},
        "selected_rows": len(clean), "orders": int(clean["order_id"].nunique()),
        "units_sold": int(clean["quantity"].sum()),
        "revenue_paise": int(clean["line_total_paise"].sum()),
        "revenue_inr": round(float(clean["revenue_inr"].sum()), 2),
        "demo_orders": int(clean.loc[clean["is_demo"].eq(1), "order_id"].nunique()),
        "most_popular_item": None if items.empty else str(items.iloc[0]["item_name"]),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    draw_charts(items, daily, args.out)
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
