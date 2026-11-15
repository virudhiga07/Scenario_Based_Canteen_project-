# Software Requirements Specification

## 1. Project identification

**Project:** College Canteen Ordering and Sales Analysis System  
**Scenario:** 3  
**Applicable register numbers:** 3, 33, 63, 93  
**Student name:** ____________________  
**Student register number:** ____________________  
**Institution / course:** ____________________

Each student submits this project in their own GitHub repository and fills in their own details. The listed register numbers identify the assignment group; they are not user accounts or shared repository owners.

## 2. Problem and objective

Manual canteen records make it difficult to calculate bills consistently, know remaining stock, and compare demand over time. The system maintains a menu, accepts multi-item orders, records completed sales, and provides item and daily sales analysis. Stock changes and transaction records must agree even when an order fails or two requests arrive together.

## 3. Scope and users

The intended user is a registered canteen owner/operator who signs in to manage their own menu, record sales, review completed orders, and export reports. Each account has its own canteen name, owner name, Indian mobile number, and GSTIN. A student or analyst runs the supplied Python workflow against the Java application's SQLite database or an exported sales CSV.

The browser interface is available through either the local Java server or the hosted JavaScript Worker. Java is the executable academic backend; the hosted deployment uses a Worker because the hosting runtime does not execute a JVM. Both implementations follow the same API and relational schema. The hosted and local databases are separate installations, not automatically synchronized.

Included: registration, login/logout, account-scoped canteen data, browser-bound demo OTP password recovery, responsive screens, menu maintenance, quantities on hand, cart, checkout, receipts, transaction history, sales charts, CSV export, Python preprocessing, and submission documents. Online payment processing, purchasing from suppliers, refunds, tax accounting, multiple canteen branches, staff permissions, and customer self-service accounts are outside this version. Selecting Cash, UPI, or Card records the payment method only; it does not collect or verify a payment.

## 4. Functional requirements and acceptance criteria

| ID | Requirement | Acceptance criteria | Design / evidence location |
| --- | --- | --- | --- |
| FR1 | Maintain item names, prices, and stock quantities. | An operator can add an item and edit its name, category, description, positive price, and nonnegative integer stock. Invalid values are rejected by the API. Items can be deactivated without deleting historical sales. | Menu & stock screen; `menu_items`; menu API |
| FR2 | Accept an order containing one or more food items. | The operator can add distinct items, change positive integer quantities, and submit a nonempty cart. Repeated item IDs in a request are combined before stock validation. A maximum of 50 distinct items is accepted per order. | New order screen; order API |
| FR3 | Calculate the bill automatically. | The browser displays the cart total and the server independently calculates the committed total from database prices. No client-supplied price can alter a bill. Amounts use integer paise; there are no taxes or extra fees in this version. | Checkout; `orders.total_paise`; `order_items.unit_price_paise` |
| FR4 | Update stock on completed orders. | A successful order reduces each item's stock by its ordered quantity. Header, line items, and stock changes form one atomic operation. Failed orders leave all stock and transaction records unchanged. | Order completion transaction |
| FR5 | Store transactions and generate reports. | A completed order retains its ID, timestamp, customer label, payment method, type, total, and line items. Orders can be retrieved after restarting the server. Reports show sales totals and offer CSV export. | Orders history; sales API; relational database |
| FR6 | Prevent orders exceeding available stock. | The server rejects insufficient stock with a conflict response and a useful message. Concurrent purchases cannot make stock negative. A retry with the same order ID and same contents returns the original sale without another deduction; changed contents under the same ID are rejected. | Stock constraints, atomic order completion, idempotency |
| FR7 | Retrieve and preprocess database sales with Python. | The Python workflow reads joined SQLite records or exported CSV, parses timestamps, validates numeric values, handles duplicates using the order/item key, identifies invalid rows, and writes cleaned data and a processing summary. | `analysis/` and Python execution instructions |
| FR8 | Visualize item sales, daily revenue, and popular items. | Charts aggregate quantities by item, revenue by the Asia/Kolkata business date, and items ranked by quantity. Python writes chart files; the browser provides interactive date-range reporting. Empty input is handled without fabricated sales. | Sales reports screen; Python chart outputs |

| FR9 | Register and authenticate a canteen account. | Registration accepts a 2–100 character canteen name and owner name, a mobile number normalized to any 10 digits, a 15-character alphanumeric GST value, and an 8–128 character password for this demo. Mobile and GSTIN are unique. Registration and valid login create an authenticated session; logout invalidates it. GST validation does not verify government registration. | Auth screens; `/api/auth/*`; `accounts`, `auth_sessions` |
| FR10 | Isolate each account's business data. | Every menu, order, and sales API operation requires authentication and derives ownership from the server session. Account A cannot read or modify Account B's records, including by guessing IDs. New accounts receive 12 initial menu entries and zero sales. Legacy rows with a null account ID remain preserved and hidden, without automatic ownership assignment. | Account-scoped API queries; `menu_items.account_id`; `orders.account_id` |
| FR11 | Recover a password using a verification challenge. | Default demo mode returns a clearly labelled six-digit code only to a browser previously registered or signed in to that account and still holding its recovery cookie. No SMS is sent in this mode. The challenge expires after 10 minutes, permits at most five attempts, and can be consumed once. Successful reset changes the salted password hash, revokes all sessions and recovery devices, and requires a fresh login. Optional SMS mode requires configured Twilio Verify credentials. | Forgot/reset screens; recovery challenge and device tables |
| FR12 | Support responsive authentication and operator screens. | Login, registration, recovery, menu, order, and report views remain usable on narrow/mobile and desktop screens. Logout is reachable on mobile and desktop. Accessible errors explain invalid fields; session expiry or logout clears the cart and account data from the UI. | Responsive layouts; session handling |

## 5. Data and business rules

1. Currency is INR. Store a price of ₹35.50 as `3550` paise; convert to rupees for display only.
2. Stock represents finished portions or units available to sell, not ingredients.
3. Ordered quantity must be a positive integer. Menu stock must be a nonnegative integer. Price must be positive.
4. A sale contains at least one active item. An unknown or inactive item cannot be purchased.
5. A stored sale is completed immediately. There is no separate kitchen queue, reservation, cancellation, or refund state in this version.
6. The server owns the sale timestamp and total. Timestamps are stored in UTC; daily reporting uses Asia/Kolkata.
7. The customer label is descriptive, not an authenticated identity. Order type is `Dine-in` or `Takeaway`; payment method is `Cash`, `UPI`, or `Card`.
8. Historic item names and unit prices are stored on order lines so later menu edits do not rewrite old bills.
9. The primary key `(order_id, item_id)` permits one aggregated line per item per order. It does not mean two separate orders for the same item are duplicates.
10. New accounts start with their own 12 menu items and zero orders. Existing sample/legacy rows retain a null `account_id`; normal account APIs never expose or claim them. Offline demonstration samples remain synthetic (`is_demo = 1`); newly entered sales use `is_demo = 0`.
11. Registration creates the account and its initial menu atomically; restarting must not overwrite account edits or recreate samples.
12. Passwords are never trimmed or stored/returned in plaintext. Store salted PBKDF2-HMAC-SHA256 hashes (100,000 iterations, 16-byte salt, 32-byte output). Sessions use random 256-bit tokens stored only as SHA-256 hashes.
13. Session cookies are HttpOnly and SameSite=Strict, Secure on HTTPS, and expire after seven days. A distinct 30-day HttpOnly recovery-device cookie survives logout only to support the explicitly disclosed demo recovery flow. A successful reset revokes all sessions and recovery devices.
14. Default `AUTH_RECOVERY_MODE=demo` is a same-browser demonstration, not proof of possession of a mobile phone. Its code is disclosed only to a valid prior recovery device for that account; a different browser cannot use this flow. `AUTH_RECOVERY_MODE=sms` uses Twilio Verify when configured and reports service errors instead of pretending that a message was sent.
15. Python `--account-id` is an optional offline analysis filter. It is not an authentication or access-control boundary; a person with database file access can read that database.

## 6. Nonfunctional requirements

| Area | Requirement |
| --- | --- |
| Data integrity | Preserve foreign keys, positive quantities and prices, nonnegative stock, and atomic order writes. |
| Usability | Provide readable currency, clear availability, visible loading/errors, keyboard-operable controls, and layouts suitable for desktop and mobile screens. |
| Persistence | Use SQLite locally and D1 for the hosted application; never rely on browser storage as the sales database. |
| Validation | Enforce input validation at the server boundary, use parameterized SQL, and reject cross-origin writes when an Origin header is supplied. |
| Reproducibility | Supply dependency declarations, database scripts, sample data, run instructions, and repeatable tests. |
| Analytical correctness | Keep money calculations in paise, record preprocessing outcomes, and use one documented reporting timezone. |
| Authentication | Protect account APIs with server-validated sessions, hash passwords and session tokens, limit authentication/recovery attempts, and invalidate stale sessions. Never return password hashes through the account API. |
| Deployment | The private hosted Site access gate and the application account login are separate layers. This teaching application does not claim a production security audit. Keep optional SMS credentials server-side. |

No formal throughput, uptime, penetration-test, or accessibility-conformance certification is claimed. Such goals require deployment-specific testing.

## 7. Main use case: complete an order

**Actor:** canteen operator.  
**Preconditions:** database initialized; operator signed in; active menu items exist in that account.
**Trigger:** operator starts a new order.

1. Operator selects items and quantities.
2. Browser displays the estimated bill and availability.
3. Operator enters the customer label, order type, and payment method.
4. Browser submits an order with a stable unique ID.
5. Server validates the request, obtains current prices and stock, and completes all database changes atomically.
6. Browser displays the stored receipt and refreshes availability and sales data.

**Success:** one completed transaction exists and stock is reduced exactly once.  
**Alternatives:** invalid fields return a validation error; insufficient stock returns a conflict; a duplicate retry returns the existing receipt; an altered retry under an existing ID returns a conflict. The operator can correct the cart and retry using the appropriate order ID.

## 8. Deliverables and verification

Deliverables include the Java source, web interface, SQL schema and sample dataset, Python analysis, this SRS, design diagrams, relational model and normalization, sample requests/results, test documentation, and a root README with execution and GitHub submission instructions. Consult `TESTING.md` for actual executed checks and remaining manual checks; acceptance criteria in this document are requirements, not a claim that a test ran.
