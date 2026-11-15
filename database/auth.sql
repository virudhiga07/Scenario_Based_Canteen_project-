CREATE TABLE IF NOT EXISTS accounts (
 id TEXT PRIMARY KEY,
 canteen_name TEXT NOT NULL,
 owner_name TEXT NOT NULL,
 mobile TEXT NOT NULL UNIQUE,
 gst_number TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL,
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
 token_hash TEXT PRIMARY KEY,
 account_id TEXT NOT NULL REFERENCES accounts(id),
 expires_at INTEGER NOT NULL,
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_rate_limits (
 key TEXT PRIMARY KEY,
 window_start INTEGER NOT NULL,
 attempts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS password_reset_challenges (
 id TEXT PRIMARY KEY,
 account_id TEXT REFERENCES accounts(id),
 mobile TEXT NOT NULL,
 expires_at INTEGER NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,
 consumed INTEGER NOT NULL DEFAULT 0,
 created_at INTEGER NOT NULL,
 demo_otp_hash TEXT,
 recovery_token_hash TEXT,
 mode TEXT NOT NULL DEFAULT 'demo'
);
CREATE TABLE IF NOT EXISTS demo_recovery_devices (
 token_hash TEXT PRIMARY KEY,
 account_id TEXT NOT NULL REFERENCES accounts(id),
 expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_sessions_account_idx ON auth_sessions(account_id);
CREATE INDEX IF NOT EXISTS reset_account_idx ON password_reset_challenges(account_id);
CREATE INDEX IF NOT EXISTS recovery_account_idx ON demo_recovery_devices(account_id);
ALTER TABLE menu_items ADD COLUMN account_id TEXT REFERENCES accounts(id);
ALTER TABLE orders ADD COLUMN account_id TEXT REFERENCES accounts(id);
CREATE INDEX IF NOT EXISTS menu_account_idx ON menu_items(account_id);
CREATE INDEX IF NOT EXISTS orders_account_idx ON orders(account_id,created_at);
