# Testing document

**Project:** College Canteen Ordering and Sales Analysis System  
**Scenario:** 3 · Register numbers 3, 33, 63, 93  
**Verification date:** November 15, 2026

## Executed automated checks

The results below describe this build. Test commands create temporary test databases; they do not overwrite the operator's persistent database.

| Component | Command | Observed result |
| --- | --- | --- |
| Java compilation and HTTP/SQLite integration | `python tests/java_api_test.py` | **23 tests passed.** Suite compiles and launches Java against an isolated SQLite database. |
| Hosted Worker business logic | `npm test` | **26 tests passed.** Runs the same Worker API implementation with a local SQLite adapter implementing its D1 interface. This is not a claim that tests ran inside production D1. |
| Python preprocessing and reporting | `python -m unittest discover -s analysis -p 'test_*.py' -v` | **9 tests passed.** |
| Demonstration database creation | `python analysis/init_demo.py --db samples/canteen-demo.db` | 12 menu items, 219 synthetic completed orders, 416 sale lines created. |
| Analysis of demonstration database | `python analysis/analyze_sales.py --db samples/canteen-demo.db --out samples/analysis` | 416 valid rows, 0 rejected rows, 0 exact duplicates; 671 units; revenue ₹29,780.00; most popular item Masala Chai. |
| SQLite foreign-key check | `PRAGMA foreign_key_check;` on sample database | No violations returned. |
| Bill reconciliation | Compare each order total with the sum of its line amounts | No mismatches returned. |
| Generated chart inspection | Open `samples/analysis/daily_revenue.png` | Rendered successfully with seven India reporting dates and labelled INR revenue. |

Dependency versions used for the Python run were pandas 2.2.3 and Matplotlib 3.10.8 on Python 3.12. The requirements file permits compatible major versions.

## Requirement coverage and expected behavior

| ID | Requirement / case | Test evidence and expected outcome |
| --- | --- | --- |
| T01 / FR1 | Add/edit menu values | Java and Worker suites check valid menu writes, invalid fields, bounds and deactivation. No negative stock or zero/negative price is accepted. |
| T02 / FR2 | More than one item in a bill | Java and Worker tests submit multiple lines and retrieve all completed lines. |
| T03 / FR3 | Server-calculated bill | Tests assert that quantities multiplied by stored menu prices produce the order total. Client values do not determine the bill. |
| T04 / FR4 | Stock deductions and persistence | Successful order tests read back remaining stock, order header and line items. A checkout updates them together. |
| T05 / FR5 | Stored transaction retrieval | Tests retrieve orders and joined sales records. Historical name and price preservation is tested after menu changes. |
| T06 / FR6 | Insufficient stock in one line | A multi-item failure leaves all stocks and order tables unchanged. |
| T07 / FR6 | Duplicate item IDs in one request | Quantities are combined before checking inventory; splitting one item over several lines cannot evade the limit. |
| T08 / FR6 | Concurrent requests for the last unit | Only one sale succeeds; stock cannot become negative. Java and Worker suites exercise concurrent calls. |
| T09 / FR6 | Repeat checkout with identical ID/content | The existing receipt is returned and stock is deducted once. Different contents under the same ID return a conflict. The Worker suite also checks simultaneous identical retries. |
| T10 / FR2–6 | Invalid or malformed requests | Empty/invalid orders, unknown or inactive items, invalid values and malformed JSON are rejected. Cross-origin browser writes are rejected when Origin is supplied. |
| T11 / FR7 | Multi-item preprocessing | Two item rows sharing an order ID remain separate; distinct order counts stay correct. |
| T12 / FR7 | Exact and conflicting duplicates | Exact duplicates are removed; conflicting records sharing an order/item key are quarantined rather than silently selected. |
| T13 / FR7 | Invalid analytical values | Invalid timestamps, negative/fractional quantities, inconsistent totals and invalid demo flags are rejected with reasons. |
| T14 / FR7–8 | Reporting timezone | A UTC timestamp after 18:30 is grouped into the following India calendar day. |
| T15 / FR8 | Missing dates and renamed items | Missing days between observations have zero revenue; item grouping uses stable IDs across historical renames. |
| T16 / FR8 | Empty reports | An empty selected dataset gives zero totals, no popular-item claim and labelled empty charts. |

## Account and recovery coverage

The Java suite adds 10 account checks. The Worker suite adds 15: salted hashes and protected cookies, field validation, duplicate accounts, server logout, unauthorized reads, cross-account reads/updates/orders, browser-bound demo OTP, one-time reset and session/device revocation, invalid/expired codes, resend/attempt limits, concurrent reset, session expiry, cross-origin writes, throttling, missing SMS configuration and legacy-record isolation. Python additionally verifies bound SQL and CSV account filtering. No real SMS was sent.

Frontend syntax, form templates, demo mobile/GST length checks, logout clearing and stale-request/session transitions were checked through Node source/VM smoke checks. Responsive CSS includes phone/tablet/laptop breakpoints and larger touch controls. Actual rendered browser verification remains pending because the provided browser infrastructure was unavailable.

## Sample inputs and observed outputs

- `samples/java-request.json` and `samples/java-response.json` record an actual Java demonstration checkout. Two Masala Dosas at ₹60 and one Masala Chai at ₹15 produced a bill of **₹135.00** with stored line snapshots.
- `samples/order-request.json` is an additional documented example request; the README explicitly distinguishes it from an executed request.
- `samples/analysis/summary.json` and the CSV/PNG files are actual outputs from the included synthetic dataset.

No automated test sends a real payment. Selecting a payment method records metadata only.

## Hosted build and publication checks

The account-enabled built Worker served its embedded interface assets, rejected an unauthenticated menu request with HTTP 401, and successfully registered a test account in a temporary database. New accounts receive their own starter menu without sample transactions. The previous deployment and database schema were verified; account migration/publication results are recorded after the final deployment. The managed browser relay timed out and the browser tool could not initialize; visual and interactive browser QA remain unverified.

The Java suite also downloads the submission ZIP and verifies required deliverables, valid archive checksums, and exclusion of runtime dependency and database folders.

## Browser/manual acceptance checklist

The following checklist is supplied for student review and demonstration. It is not marked as executed by the backend/Python suites. Browser QA and deployment results, when performed, must be recorded separately with the browser and viewport used.

| Check | Procedure | Expected result |
| --- | --- | --- |
| First load | Start Java; open `http://127.0.0.1:8080`. | Sign-in screen appears; account creation opens the account-specific menu and empty sales dashboard. |
| Account and logout | Create an account, sign out, and sign in again. | Account fields validate; logout revokes the server session and clears visible data. |
| Demo recovery | In the same authorized browser, sign out, choose Forgot password, enter the displayed code and new password. | Code is labelled demo/no SMS; reset succeeds once, revokes all sessions and returns to login. |
| Other browser | Try that recovery in a private window. | Same-browser demo restriction is explained without exposing a code. |
| Checkout | Add two items, change quantities, complete an order. | Total updates; stored receipt appears; stock and dashboard refresh. |
| Stock limit | Attempt to add more than remaining stock. | Clear message and no completed order exceeding stock. |
| Menu maintenance | Add an item, change price and stock, deactivate it. | New values persist after refresh; inactive items cannot be bought. |
| Sales report | Change reporting range, export CSV, run Python with `--csv`. | Report and export match the selected data; Python reads the documented columns. |
| Narrow viewport | Review at 360/390px phone, 768px tablet, 1366px laptop and 1440px desktop widths and navigate all sections. | Controls and text remain usable; important information is not clipped. |
| Keyboard | Navigate controls with Tab, submit forms, close dialogs with Escape. | Focus is visible; controls and dialogs are usable without a pointer. |
| Restart persistence | Complete a sale, stop Java, start it against the same DB. | Sale and remaining stock survive; seeding does not overwrite them. |
| Submission pack | Download `/submission.zip` or use the delivered ZIP. | Required source, documents and sample artifacts are present and readable. |

## Limits

These are functional and integrity checks for an educational application. They do not establish production load capacity, security certification, browser/accessibility conformance, or real-payment correctness. The Worker tests use the local D1-compatible adapter; deployment success and production D1 behavior require their own recorded checks. The hosted and local databases are separate, so they are not expected to contain identical user-created records.

## Registration format regression

Java and Worker tests register and log in with demo values matching the reported screenshot: mobile `1234567890`, GST `1234567890OKJHG`, and a password meeting the 8-character minimum. Invalid lengths and non-digit mobile/non-alphanumeric GST input remain rejected. Auth forms use `novalidate` plus explicit field messages so the browser’s generic format tooltip no longer blocks the form.
