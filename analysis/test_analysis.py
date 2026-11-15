"""Meaningful edge cases for transaction preprocessing and reporting."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analyze_sales import aggregate, main, preprocess, retrieve_database


class SalesAnalysisTests(unittest.TestCase):
    def row(self, **changes):
        row = dict(order_id="o1", created_at="2026-11-14T20:00:00Z", item_id=1, item_name="Masala dosa", quantity=2, unit_price_paise=6000, line_total_paise=12000, is_demo=0)
        return row | changes

    def test_multiple_items_in_same_order_are_preserved(self):
        clean, rejected, report = preprocess(pd.DataFrame([self.row(), self.row(item_id=2, item_name="Tea")]))
        self.assertEqual(len(clean), 2)
        self.assertEqual(len(rejected), 0)
        self.assertEqual(aggregate(clean)[1].iloc[0]["orders"], 1)

    def test_india_midnight_and_exact_duplicate(self):
        clean, _, report = preprocess(pd.DataFrame([self.row(), self.row()]))
        self.assertEqual(clean.iloc[0]["sale_date"], "2026-11-15")
        self.assertEqual(report["exact_duplicates_removed"], 1)

    def test_conflicting_duplicate_is_quarantined(self):
        clean, rejected, _ = preprocess(pd.DataFrame([self.row(), self.row(quantity=1, line_total_paise=6000)]))
        self.assertTrue(clean.empty)
        self.assertEqual(len(rejected), 2)
        self.assertIn("conflicting", rejected.iloc[0]["rejection_reason"])

    def test_invalid_data_is_not_silently_counted(self):
        raw = [self.row(), self.row(order_id="bad-date", created_at="never"), self.row(order_id="bad-quantity", quantity=-2), self.row(order_id="fraction", quantity=1.5), self.row(order_id="mismatch", line_total_paise=1), self.row(order_id="bad-demo", is_demo=2)]
        clean, rejected, report = preprocess(pd.DataFrame(raw))
        self.assertEqual(len(clean), 1)
        self.assertEqual(len(rejected), 5)
        self.assertEqual(clean["line_total_paise"].sum(), 12000)

    def test_daily_missing_dates_are_zero_filled(self):
        clean, _, _ = preprocess(pd.DataFrame([self.row(), self.row(order_id="o2", created_at="2026-11-16T20:00:00Z")]))
        _, daily = aggregate(clean)
        self.assertEqual(list(daily["revenue_inr"]), [120, 0, 120])

    def test_historical_names_group_by_stable_item_id(self):
        clean, _, _ = preprocess(pd.DataFrame([self.row(), self.row(order_id="o2", item_name="Dosa", created_at="2026-11-16T10:00:00Z")]))
        items, _ = aggregate(clean)
        self.assertEqual(len(items), 1)
        self.assertEqual(items.iloc[0]["units"], 4)
        self.assertEqual(items.iloc[0]["item_name"], "Dosa")

    def test_empty_selection_still_generates_charts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pd.DataFrame([self.row(is_demo=1)]).to_csv(root / "input.csv", index=False)
            summary = main(["--csv", str(root / "input.csv"), "--out", str(root / "out"), "--exclude-demo"])
            self.assertEqual(summary["revenue_paise"], 0)
            self.assertIsNone(summary["most_popular_item"])
            self.assertTrue((root / "out" / "daily_revenue.png").is_file())

    def test_account_filter_scopes_database_and_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "accounts.db"
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE orders (id TEXT, account_id TEXT, created_at TEXT, customer_name TEXT, order_type TEXT, payment_method TEXT, is_demo INTEGER)")
                connection.execute("CREATE TABLE order_items (order_id TEXT, item_id INTEGER, item_name TEXT, quantity INTEGER, unit_price_paise INTEGER)")
                connection.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", [("o1", "account-a", "2026-11-14T20:00:00Z", "A", "Dine-in", "Cash", 0), ("o2", "account-b", "2026-11-14T20:00:00Z", "B", "Dine-in", "Cash", 0), ("legacy", None, "2026-11-14T20:00:00Z", "Old", "Dine-in", "Cash", 1)])
                connection.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", [("o1", 1, "Dosa", 2, 6000), ("o2", 2, "Tea", 1, 1500), ("legacy", 3, "Rice", 1, 8000)])
            selected = retrieve_database(db, "account-a")
            self.assertEqual(list(selected["order_id"]), ["o1"])
            self.assertTrue(retrieve_database(db, "account-a' OR 1=1 --").empty)
            retrieve_database(db).to_csv(root / "all.csv", index=False)
            summary = main(["--csv", str(root / "all.csv"), "--account-id", "account-b", "--out", str(root / "out")])
            self.assertEqual(summary["orders"], 1)
            self.assertEqual(summary["revenue_paise"], 1500)
            self.assertEqual(summary["selection"]["account_id"], "account-b")

    def test_missing_columns_fail_explicitly(self):
        with self.assertRaisesRegex(ValueError, "Missing required columns"):
            preprocess(pd.DataFrame({"order_id": ["a"]}))


if __name__ == "__main__":
    unittest.main()
