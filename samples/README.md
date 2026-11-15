# Sample inputs and outputs

All data in this directory is synthetic.

- `order-request.json` is a valid HTTP `POST /api/orders` body for the seeded menu. It requests two Masala Dosas and one Masala Chai. Reusing its ID with the same content returns the same existing sale. Use a new UUID for a new sale.
- `canteen-demo.db` is the reproducible SQLite database created from the SQL schema and shared seed file. It contains the 219 sample orders only.
- `analysis/` contains actual generated Python reports and PNG charts from that database.
- Java integration request/response examples and evidence are in the Java sample files when provided.

Example from a second terminal while Java is running:

```sh
curl -sS http://127.0.0.1:8080/api/menu
curl -sS -X POST http://127.0.0.1:8080/api/orders \
  -H 'Content-Type: application/json' --data-binary @samples/order-request.json
```

The server chooses the current timestamp and authoritative menu prices. An insufficient-stock response is HTTP 409 and contains an `error` message; it leaves the entire order uncommitted. The checked-in order body is an example input, not a claim that this request has been executed against your database.

The sample analysis produced 416 valid sale lines, 219 distinct orders, 671 units and revenue of 2,978,000 paise (₹29,780.00). Masala Chai ranked first by units sold. See `analysis/summary.json` for machine-readable output.

Current APIs require login. The recorded request/response files show the earlier executed sample checkout; item IDs in a new account can differ. Use the current account menu IDs and an authenticated cookie jar when using `java-curl.sh`. Keep cookie jars and private request files outside the repository.
