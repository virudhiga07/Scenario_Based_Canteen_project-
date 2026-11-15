# Account access and password recovery

## Register and sign in

Registration collects canteen name, owner name, Indian mobile number, GSTIN and password. It creates a canteen account and signs that browser in. Login uses mobile number and password.

| Field | Server validation |
| --- | --- |
| Canteen name / owner name | Trimmed length 2–100 characters. |
| Mobile | Exactly 10 digits after normalization; optional +91 and common spaces/hyphens are accepted. |
| GSTIN | Exactly 15 alphanumeric characters, normalized to uppercase. Demo values are accepted without state/PAN/checksum validation; this does not verify government registration or ownership. |
| Password | 8–128 characters. Password whitespace is preserved. |

Mobile number and GSTIN are unique per account. The application stores salted PBKDF2-SHA256 hashes with 100,000 iterations, a random 16-byte salt and a 32-byte output. It never stores or returns plaintext passwords. There are no default shared passwords or automatic account assignments.

Each new account receives its own 12 starter menu items and no orders. All menu, order and sales API reads/writes require a current session and are scoped to that account. Knowledge of another account's item or order ID does not grant access. Historical rows without an account ID remain preserved, unassigned and hidden from these APIs.

## Sessions and logout

`canteen_session` is an opaque random 256-bit cookie with HttpOnly, SameSite=Strict and Path=/; it is Secure when served over HTTPS. The database stores its SHA-256 hash, not the raw token. Sessions expire after seven days. Logout deletes the current server session and cookie, and clears the account's operator UI/cart data. An expired session requires sign-in again.

Demo recovery uses a separate `canteen_demo_recovery` cookie. It is issued after successful registration or password login, has the same browser cookie protections, and expires after 30 days. Its SHA-256 hash is bound to the account in `demo_recovery_devices`. Logout intentionally retains this recovery cookie so that the classroom Forgot password flow can be demonstrated after signing out. It is not an authenticated application session and cannot read sales or place orders.

## Demo OTP: no SMS is sent

`AUTH_RECOVERY_MODE=demo` is the default, approved demonstration behavior. The interface labels the code as a demo and states that no SMS was sent.

1. Register or sign in successfully in a browser.
2. Log out, then choose **Forgot password** in that same browser and enter the account's mobile number.
3. The server verifies the browser's account-bound recovery cookie before returning a six-digit demo OTP to that browser.
4. Enter the displayed code and a new 8–128 character password within 10 minutes.
5. After a successful reset, sign in with the new password. All previous sessions and recovery-device records are revoked; a new successful login creates fresh cookies.

A different browser, private window, cleared cookie or expired recovery device cannot request or use that account's demo OTP. The request fails with the same-browser explanation. Copying a code to another browser does not authorize reset. If access to the authorized browser is lost, demo recovery cannot recover the account; configure real SMS verification before relying on remote recovery.

Codes use cryptographic randomness. The database stores a hash of the challenge ID and code. Each challenge expires in 600 seconds, allows at most five verification attempts, and is consumed atomically once. A new challenge invalidates an older unconsumed challenge for that account. Rate limits apply to requesting and verifying codes. This demonstrates reset mechanics; it does not prove mobile-number ownership.

## Future SMS delivery

Set these **server-side environment variables** through the deployment's environment settings, without putting values into source code, browser JavaScript, documentation or Git:

| Variable | Purpose |
| --- | --- |
| `AUTH_RECOVERY_MODE` | Set to `sms` to explicitly enable the provider flow; `demo` is the default. |
| `TWILIO_ACCOUNT_SID` | Twilio account identifier. |
| `TWILIO_AUTH_TOKEN` | Twilio server authentication secret. |
| `TWILIO_VERIFY_SERVICE_SID` | Twilio Verify service configured for six-digit SMS verification. |

The server uses Twilio Verify to send/check codes for `+91` numbers. SMS mode never returns a demo OTP. With missing configuration, recovery returns HTTP 503 and explains that SMS is not configured; it does not pretend to send a message. Provider failures are reported as failures. No real credentials or real SMS delivery were supplied or tested for this project.

For an unknown mobile in correctly configured SMS mode, the application returns a generic challenge response without sending a verification message. Correct codes must still be provider-approved and bound to a valid, unexpired challenge. Successful SMS reset also revokes sessions and recovery-device records.

## API summary

| Method and path | Behavior |
| --- | --- |
| `GET /api/auth/session` | Returns public account fields or null, SMS configuration availability and recovery mode. |
| `POST /api/auth/register` | Validates fields, creates an account, starter menu and session. |
| `POST /api/auth/login` | Verifies mobile/password and sets session/recovery cookies. |
| `POST /api/auth/logout` | Revokes current session; safe when already logged out. |
| `POST /api/auth/forgot-password` | Creates a controlled demo or SMS recovery challenge. |
| `POST /api/auth/reset-password` | Validates and consumes challenge, changes password and revokes sessions/devices. |

Authentication errors use JSON with an `error` message. Protected data endpoints return HTTP 401 without a valid session. Same-origin checks reject cross-origin browser writes. Rate limits restrict registration, login, code sending and verification; these limits are not a general denial-of-service protection system.

## Offline data and migration

`database/auth.sql` adds authentication tables and nullable `account_id` references to existing menu/order tables. Applied SQL migrations must not be rerun blindly because ALTER TABLE additions are not repeatable. The application startup/migration path manages application.

Existing null-account rows remain archived, not deleted or automatically claimed. New orders inherit their signed-in account on the server; clients cannot choose ownership. Account ID is selected from the session for every protected query.

Python reads SQLite or exported CSV as an offline tool with filesystem access. `--account-id` is a useful explicit reporting filter, not an authentication boundary. Signed-in web exports are already account-scoped. Protect the database file and exported reports as appropriate for their contents.
