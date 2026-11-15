# Python sales analysis

Run from the project root with Python 3.10 or later:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python analysis/init_demo.py --db data/canteen.db
python analysis/analyze_sales.py --db data/canteen.db --out analysis/output
python -m unittest discover -s analysis -p 'test_*.py' -v
```

Skip `init_demo.py` when the Java application has already created that database. It refuses to overwrite existing files. On Windows activate with `.venv\Scripts\activate`.

`--db` queries SQLite using a read-only connection and a join of completed orders and their historical line items. It does not use current menu prices to calculate historical revenue. The hosted app uses D1; download its sales CSV in **Sales reports → Export CSV**, then run:

```sh
python analysis/analyze_sales.py --csv downloads/canteen-sales.csv --out analysis/output
```

For a current multi-account SQLite database, select the intended account explicitly:

```sh
python analysis/analyze_sales.py --db data/canteen.db --account-id YOUR-ACCOUNT-ID --out analysis/output
```

This is an offline administrative report tool, not a runtime login mechanism. Anyone who can read the database file can analyze it. Without `--account-id` the query includes every account and preserved, unassigned historical records. With the flag, SQL uses a bound parameter and excludes other accounts and null ownership. Explicit filtering on an older database without the `account_id` column fails clearly instead of returning unfiltered records.

For a CSV containing an `account_id` column the same flag selects matching rows before preprocessing. The browser export is already scoped to the signed-in account and does not need that flag. If a CSV has no account column, requesting the flag fails with an explanatory error.

Date and demonstration filters are optional: `--start 2026-11-09 --end 2026-11-15 --exclude-demo`. Dates are inclusive in Asia/Kolkata. Use `--exclude-demo` to analyze only orders you completed yourself. Omitting it includes clearly marked sample transactions.

## Preprocessing

1. Require order ID, timestamp, item ID, item name, quantity and unit price columns.
2. Parse timestamps as UTC; derive the reporting day in Asia/Kolkata.
3. Validate positive integral item IDs, quantities and prices, valid demo flags, and line-total arithmetic.
4. Remove exact duplicate lines. The natural key is `(order_id, item_id)`, so multiple items in an order remain intact.
5. Quarantine conflicting duplicate keys and invalid rows in `rejected_rows.csv` with reasons. Source records remain untouched.
6. Filter dates/demo records, then group revenue by day and sales by stable item ID. The latest recorded name labels items after a rename. Fill missing days with zero within the selected observed period.

## Outputs

- `cleaned_sales.csv`: validated selected sales with India reporting dates and rupee revenue.
- `rejected_rows.csv`: rejected input records with explicit reasons.
- `item_sales.csv`: units and revenue per item.
- `daily_revenue.csv`: daily revenue, distinct order count and units.
- `summary.json`: row counts, exclusions, totals and most popular item.
- `item_sales.png`: item-wise revenue chart.
- `daily_revenue.png`: daily revenue line chart.
- `popular_items.png`: most popular items by unit quantity.

Empty selections produce zero-valued summaries and labelled empty charts. Sample output in `samples/analysis/` is generated from the bundled November 9–15, 2026 demonstration data; it is not real college sales data.
