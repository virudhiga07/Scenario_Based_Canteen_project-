# Java application

The Java version serves the same `web/` interface and API as the hosted edition, using a local SQLite database through JDBC. This is the Java source-code deliverable for Scenario 3.

## Run

Install Java 17 or newer (a JDK), Bash, curl and sha256sum. On Windows use WSL, or run these commands in a Linux environment. From the project root:

```bash
bash java/run.sh
```

Open <http://127.0.0.1:8080>. First startup creates `data/canteen.db` and the account tables. Create an account to sign in. Each new account receives 12 starter menu items and no historical orders. Repeated starts preserve accounts, stock, menu changes and transactions. Older unassigned records remain hidden from account APIs.

The first build downloads four version-pinned dependencies from Maven Central, then verifies their SHA-256 hashes against `java/dependencies.tsv`. Subsequent builds reuse the checked local jars. Maven is not required. Compile separately with `bash java/build.sh`.

To use a separate database or port:

```bash
bash java/run.sh --db data/live.db --port 8081
```

After signing in, maintain menu items through **Menu & stock**. Options are `--db PATH`, `--port PORT`, `--host HOST`, and `--root PROJECT_DIRECTORY`. The former `--seed` option is accepted for command compatibility and does not import shared history. The default host is loopback. Use HTTPS when hosting externally so account cookies receive the Secure attribute.

## Implementation details

- `java/src/CanteenServer.java` uses the JDK HTTP server, Gson for JSON, prepared JDBC statements, and SQLite foreign-key/check constraints.
- `BEGIN IMMEDIATE` acquires a database writer lock before inventory is read. A successful order writes its header, line snapshots, and stock changes together. Any failure rolls the whole operation back.
- Duplicate food IDs are aggregated before stock checking. Quantities, names, prices, stock, and request sizes have explicit bounds. The server calculates totals from current menu prices in integer paise.
- Clients assign a UUID to each checkout. A retry with the same normalized order returns its existing receipt without charging stock again. Reusing a UUID for different contents returns HTTP 409.
- Completed orders retain the item name and price at purchase time; later menu edits do not rewrite sales history.
- Cross-origin browser writes are rejected. Application errors return JSON with an `error` property.
- Schema installation runs at startup, outside request handlers. Authentication table setup and ownership-column migration run before serving requests. Starter menu copies are created inside each account registration transaction.

See [API contract](API-CONTRACT.md), [shared SQL schema](../database/schema.sql), and [Java HTTP tests](../tests/java_api_test.py).

## Verification

```bash
python3 tests/java_api_test.py
```

The suite builds and starts the Java server against a temporary database and removes that database afterward. Twenty-three tests cover multi-item bills, inventory changes, sales retrieval, insufficient-stock rollback, duplicate item aggregation, idempotency, concurrent last-unit sales, menu deactivation, invalid input, malformed JSON, browser Origin checks, a safe source ZIP download, account validation and isolation, password hashing, logout, demo OTP recovery, expiry, attempt limits and session revocation. All 23 passed in this build.

The Project docs download is generated from authored files on demand, so it also works in an extracted local project. It excludes dependencies, live databases, caches, and hosting identity.

Authentication is implemented in `java/src/CanteenAuth.java`. The default demo OTP is displayed only in a browser previously authorized for that account. See [account and recovery instructions](AUTHENTICATION.md). Real SMS delivery requires the documented Twilio environment settings.

For classroom account creation, any 10-digit mobile number and a 15-character alphanumeric GST value are accepted. GST input is normalized to uppercase without state/PAN/checksum validation. Passwords must contain 8–128 characters; whitespace is preserved. These checks permit demonstration values and do not verify a phone number or GST registration.
