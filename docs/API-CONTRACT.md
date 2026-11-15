# Current account boundary

All menu/order/sales endpoints below require a valid session and use the signed-in account ID on the server. See [authentication routes](AUTHENTICATION.md). New accounts receive independent menu templates with no orders. The original sample initialization description below applies only to the standalone historical fixture; hosted request handlers no longer initialize shared sample records.

# Shared API and database contract
All amounts are integer Indian paise; timestamps ISO-8601 UTC. Reporting day is Asia/Kolkata.

Tables:
- menu_items(id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', price_paise INTEGER NOT NULL CHECK(price_paise>0), stock INTEGER NOT NULL CHECK(stock>=0), image TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1)
- orders(id TEXT PRIMARY KEY, customer_name TEXT NOT NULL, order_type TEXT NOT NULL, payment_method TEXT NOT NULL, created_at TEXT NOT NULL, total_paise INTEGER NOT NULL CHECK(total_paise>0), is_demo INTEGER NOT NULL DEFAULT 0)
- order_items(order_id TEXT REFERENCES orders(id), item_id INTEGER REFERENCES menu_items(id), item_name TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0), unit_price_paise INTEGER NOT NULL CHECK(unit_price_paise>0), PRIMARY KEY(order_id,item_id))
- app_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)

API same origin:
GET /api/menu -> {items: [menu_items rows]}
POST /api/menu -> {item}; body {name,category,description,price_paise,stock,image} (image optional string identifier)
PATCH /api/menu/:id -> {item}; body full fields incl active (optional); validate bounded integers
GET /api/orders -> {orders:[{...orders row,items:[{item_id,item_name,quantity,unit_price_paise}]}]} newest first
POST /api/orders -> {order: {...row,items:[...]}}; body {id: UUID idempotency key, customer_name, order_type: 'Dine-in'|'Takeaway', payment_method:'Cash'|'UPI'|'Card',items:[{item_id,quantity}]}. Aggregate duplicate item IDs, max 50 distinct items, enforce stock and server-calculated prices with atomic transaction. Unknown/deactivated items rejected. On same id with different order content reject 409, same content return existing. No tax or fees.
GET /api/sales -> {lines:[{order_id,created_at,customer_name,order_type,payment_method,is_demo,item_id,item_name,quantity,unit_price_paise,line_total_paise}]} (join order_items/orders)
GET /api/health -> {ok:true}
Errors: {error:string}, HTTP 400 validation / 404 unknown / 409 stock conflict. Malformed JSON 400. Reject cross-origin writes where Origin header present.

Initial seeded demo workspace: menu seed and clearly marked sample historical orders (is_demo=1), once per database, app_meta key initialized. Product UI shows 'Demo workspace' and explains sample records. POST-created orders is_demo=0. Seed never overwrites user changes. Seed data will be in database/seed.json supplied by root; same tables in database/schema.sql. Schema installed before server requests, never in request handlers.
Frontend: web/index.html + web/styles.css + web/app.js (plain browser ES module) served by both Worker and Java; all endpoints above shared. Root will bundle hosted worker. Java serves relative ../web or web path configurable. Submission zip link /submission.zip.
