CREATE TABLE IF NOT EXISTS menu_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 100),
 category TEXT NOT NULL CHECK(length(category) BETWEEN 1 AND 40),
 description TEXT NOT NULL DEFAULT '',
 price_paise INTEGER NOT NULL CHECK(price_paise BETWEEN 1 AND 10000000),
 stock INTEGER NOT NULL CHECK(stock BETWEEN 0 AND 1000000),
 image TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY,
 customer_name TEXT NOT NULL,
 order_type TEXT NOT NULL CHECK(order_type IN ('Dine-in','Takeaway')),
 payment_method TEXT NOT NULL CHECK(payment_method IN ('Cash','UPI','Card')),
 created_at TEXT NOT NULL,
 total_paise INTEGER NOT NULL CHECK(total_paise > 0),
 is_demo INTEGER NOT NULL DEFAULT 0 CHECK(is_demo IN (0,1))
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS order_items (
 order_id TEXT NOT NULL REFERENCES orders(id),
 item_id INTEGER NOT NULL REFERENCES menu_items(id),
 item_name TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 10000),
 unit_price_paise INTEGER NOT NULL CHECK(unit_price_paise > 0),
 PRIMARY KEY(order_id,item_id)
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS orders_created_at_idx ON orders(created_at);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS order_items_item_idx ON order_items(item_id);
--> statement-breakpoint
