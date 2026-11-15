#!/usr/bin/env python3
"""Integration tests for the Java/SQLite canteen server (Python standard library only).

Run from the project root:
    python3 tests/java_api_test.py

Each run launches a Java server on an available loopback port, creates a temporary
SQLite database without demo records, and removes both when the suite ends.
"""
from __future__ import annotations

import concurrent.futures
import json
import io
import zipfile
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


class JavaApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="canteen-java-tests-")
        cls.db_path = Path(cls.temp.name) / "test.db"
        cls.log_path = Path(cls.temp.name) / "server.log"
        cls.log = cls.log_path.open("w", encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.process = subprocess.Popen(
            ["bash", str(ROOT / "java/run.sh"), "--db", str(cls.db_path),
             "--port", str(cls.port), "--seed", "none"],
            cwd=ROOT, stdout=cls.log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                break
            try:
                with urllib.request.urlopen(cls.base + "/api/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError):
                time.sleep(0.15)
        cls.stop_server()
        raise RuntimeError("Java server did not start:\n" + cls.log_path.read_text())

    @classmethod
    def stop_server(cls):
        if getattr(cls, "process", None) and cls.process.poll() is None:
            os.killpg(cls.process.pid, signal.SIGTERM)
            try:
                cls.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(cls.process.pid, signal.SIGKILL)
                cls.process.wait(timeout=5)
        if getattr(cls, "log", None):
            cls.log.close()

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()
        cls.temp.cleanup()

    counter = 0

    @staticmethod
    def gst(number):
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        stem = f"27AAAAA{number:04d}A1Z"
        factor, total = 2, 0
        for char in reversed(stem):
            digit = alphabet.index(char) * factor
            total += digit // 36 + digit % 36
            factor = 1 if factor == 2 else 2
        return stem + alphabet[(36 - total % 36) % 36]

    def setUp(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM auth_rate_limits")
        type(self).counter += 1
        self.mobile = f"98765{self.counter:05d}"
        self.password = "Canteen test password"
        self.cookie = ""
        payload = {"canteen_name": "Test Canteen", "owner_name": "Test Owner", "mobile": self.mobile,
                   "gst_number": self.gst(self.counter), "password": self.password}
        status, body = self.request("POST", "/api/auth/register", payload)
        self.assertEqual(status, 201, body)
        self.account = body["account"]
        self.cookie = "; ".join(header.split(";", 1)[0] for header in self.last_cookies)

    def request(self, method, path, payload=None, *, raw=None, origin=None, cookie=None):
        body = raw if raw is not None else (
            json.dumps(payload).encode("utf-8") if payload is not None else None
        )
        headers = {"Content-Type": "application/json", "Cookie": self.cookie if cookie is None else cookie}
        if origin is not None:
            headers["Origin"] = origin
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                self.last_cookies = response.headers.get_all("Set-Cookie") or []
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_source_download_contains_deliverables_without_runtime_files(self):
        with urllib.request.urlopen(self.base + "/submission.zip", timeout=15) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "application/zip")
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                names = archive.namelist()
                self.assertIn("virudhigakv-canteen/java/src/CanteenServer.java", names)
                self.assertIn("virudhigakv-canteen/docs/SRS.md", names)
                self.assertIn("virudhigakv-canteen/samples/canteen-demo.db", names)
                self.assertFalse(any("/lib/" in n or "/data/" in n or "/.git/" in n for n in names))
                self.assertNotIn("project_id", json.loads(archive.read("virudhigakv-canteen/.openai/hosting.json")))
                self.assertIsNone(archive.testzip())

    def item(self, name="Masala dosa", price=4500, stock=12):
        status, data = self.request("POST", "/api/menu", {
            "name": f"{name} {uuid.uuid4().hex[:6]}", "category": "Meals",
            "description": "Integration test item", "price_paise": price,
            "stock": stock, "image": "dosa",
        })
        self.assertIn(status, (200, 201), data)
        return data["item"]

    def stock(self, item_id):
        status, data = self.request("GET", "/api/menu")
        self.assertEqual(status, 200)
        return next(row["stock"] for row in data["items"] if row["id"] == item_id)

    def order(self, *items, **overrides):
        payload = {
            "id": str(uuid.uuid4()), "customer_name": "Test Student",
            "order_type": "Dine-in", "payment_method": "Cash",
            "items": [{"item_id": item_id, "quantity": quantity} for item_id, quantity in items],
        }
        payload.update(overrides)
        return payload

    def assert_error(self, status, data, expected):
        self.assertEqual(status, expected, data)
        self.assertIsInstance(data.get("error"), str)
        self.assertTrue(data["error"])

    def test_auth_registration_fields_hashes_and_session(self):
        self.assertEqual(self.account["mobile"], self.mobile)
        self.assertNotIn("password_hash", self.account)
        with sqlite3.connect(self.db_path) as conn:
            stored = conn.execute("SELECT password_hash FROM accounts WHERE id=?", (self.account["id"],)).fetchone()[0]
            self.assertTrue(stored.startswith("pbkdf2-sha256$100000$"))
            self.assertNotIn(self.password, stored)
            token_hash = conn.execute("SELECT token_hash FROM auth_sessions WHERE account_id=?", (self.account["id"],)).fetchone()[0]
            self.assertEqual(len(token_hash), 64)
            self.assertNotIn(token_hash, self.cookie)
        status, session = self.request("GET", "/api/auth/session")
        self.assertEqual(status, 200)
        self.assertEqual(session["account"], self.account)
        self.assertEqual(session["recovery_mode"], "demo")
        self.assertEqual(len(self.request("GET", "/api/menu")[1]["items"]), 12)
        self.assertEqual(self.request("GET", "/api/orders")[1]["orders"], [])

    def test_auth_required_for_all_business_data(self):
        for path in ("/api/menu", "/api/orders", "/api/sales"):
            self.assert_error(*self.request("GET", path, cookie=""), 401)
        status, body = self.request("GET", "/api/auth/session", cookie="")
        self.assertEqual(status, 200)
        self.assertIsNone(body["account"])
        self.assert_error(*self.request("POST", "/api/orders", self.order(), cookie=""), 401)

    def test_auth_invalid_registration_and_duplicate_mobile(self):
        payload = {"canteen_name": "Test Canteen", "owner_name": "Test Owner", "mobile": self.mobile,
                   "gst_number": self.account["gst_number"], "password": self.password}
        for change in ({"mobile": "123456789"}, {"mobile": "12345678901"}, {"mobile": "12345A7890"},
                       {"gst_number": "1234567890OKJH"}, {"gst_number": "1234567890OKJHGX"},
                       {"gst_number": "1234567890OKJH!"}, {"password": "short"},
                       {"owner_name": ""}, {"canteen_name": "A"}):
            self.assert_error(*self.request("POST", "/api/auth/register", dict(payload, **change)), 400)
        self.assert_error(*self.request("POST", "/api/auth/register", payload), 409)

    def test_auth_demo_registration_accepts_screenshot_values_and_eight_character_password(self):
        payload = {"canteen_name": "College Canteen", "owner_name": "virudhigakv", "mobile": "+91 12345-67890",
                   "gst_number": "1234567890okjhg", "password": "demo1234"}
        status, body = self.request("POST", "/api/auth/register", payload, cookie="")
        self.assertEqual(status, 201, body)
        self.assertEqual(body["account"]["mobile"], "1234567890")
        self.assertEqual(body["account"]["gst_number"], "1234567890OKJHG")
        status, login = self.request("POST", "/api/auth/login", {"mobile": "1234567890", "password": "demo1234"}, cookie="")
        self.assertEqual(status, 200, login)
        self.assertEqual(login["account"]["id"], body["account"]["id"])

    def test_auth_accounts_cannot_access_each_others_inventory_or_sales(self):
        item = self.item(stock=3)
        order = self.order((item["id"], 1))
        self.assertIn(self.request("POST", "/api/orders", order)[0], (200, 201))
        status, data = self.request("POST", "/api/auth/register", {"canteen_name": "Other Canteen", "owner_name": "Other Owner",
            "mobile": "9123400001", "gst_number": self.gst(9001), "password": self.password})
        self.assertEqual(status, 201, data)
        other_cookie = "; ".join(header.split(";", 1)[0] for header in self.last_cookies)
        other_menu = self.request("GET", "/api/menu", cookie=other_cookie)[1]["items"]
        self.assertNotIn(item["id"], [m["id"] for m in other_menu])
        self.assertEqual(self.request("GET", "/api/orders", cookie=other_cookie)[1]["orders"], [])
        self.assertEqual(self.request("GET", "/api/sales", cookie=other_cookie)[1]["lines"], [])
        self.assert_error(*self.request("PATCH", f'/api/menu/{item["id"]}', item, cookie=other_cookie), 404)
        self.assert_error(*self.request("POST", "/api/orders", self.order((item["id"], 1)), cookie=other_cookie), 404)
        self.assertEqual(self.stock(item["id"]), 2)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("INSERT INTO menu_items(name,category,description,price_paise,stock,image,active) VALUES('Legacy','Meals','',100,9,'',1)")
            legacy_id = cursor.lastrowid
        own_menu = self.request("GET", "/api/menu")[1]["items"]
        self.assertNotIn(legacy_id, [m["id"] for m in own_menu])

    def test_auth_logout_invalidates_session_but_keeps_demo_browser(self):
        status, body = self.request("POST", "/api/auth/logout", {})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(any("Max-Age=0" in h and h.startswith("canteen_session=") for h in self.last_cookies))
        self.assertFalse(any(h.startswith("canteen_demo_recovery=") for h in self.last_cookies))
        self.assert_error(*self.request("GET", "/api/menu"), 401)
        self.assertIsNone(self.request("GET", "/api/auth/session")[1]["account"])
        status, challenge = self.request("POST", "/api/auth/forgot-password", {"mobile": self.mobile})
        self.assertEqual(status, 200, challenge)
        self.assertTrue(challenge["demo"])

    def test_auth_login_rejects_wrong_password_and_limits_attempts(self):
        for _ in range(5):
            self.assert_error(*self.request("POST", "/api/auth/login", {"mobile": self.mobile, "password": "Wrong password"}), 401)
        self.assert_error(*self.request("POST", "/api/auth/login", {"mobile": self.mobile, "password": self.password}), 429)

    def test_auth_demo_reset_is_one_time_and_revokes_every_session(self):
        status, body = self.request("POST", "/api/auth/login", {"mobile": self.mobile, "password": self.password})
        self.assertEqual(status, 200, body)
        second_cookie = "; ".join(h.split(";", 1)[0] for h in self.last_cookies)
        status, challenge = self.request("POST", "/api/auth/forgot-password", {"mobile": self.mobile})
        self.assertEqual(status, 200, challenge)
        self.assertRegex(challenge["demo_otp"], r"^\d{6}$")
        self.assertIn("No SMS", challenge["message"])
        payload = {"mobile": self.mobile, "challenge_id": challenge["challenge_id"], "otp": challenge["demo_otp"], "password": "New canteen password"}
        wrong = "000000" if payload["otp"] != "000000" else "111111"
        self.assert_error(*self.request("POST", "/api/auth/reset-password", dict(payload, otp=wrong)), 400)
        self.assert_error(*self.request("POST", "/api/auth/reset-password", payload, cookie=""), 400)
        self.assertEqual(self.request("POST", "/api/auth/reset-password", payload)[0], 200)
        self.assert_error(*self.request("GET", "/api/menu"), 401)
        self.assert_error(*self.request("GET", "/api/menu", cookie=second_cookie), 401)
        self.assert_error(*self.request("POST", "/api/auth/reset-password", payload), 400)
        self.assert_error(*self.request("POST", "/api/auth/login", {"mobile": self.mobile, "password": self.password}), 401)
        self.assertEqual(self.request("POST", "/api/auth/login", {"mobile": self.mobile, "password": payload["password"]})[0], 200)
        with sqlite3.connect(self.db_path) as conn:
            stored = conn.execute("SELECT demo_otp_hash,consumed FROM password_reset_challenges WHERE id=?", (payload["challenge_id"],)).fetchone()
            self.assertNotEqual(stored[0], payload["otp"])
            self.assertEqual(stored[1], 1)

    def test_auth_demo_different_browser_cannot_request_code_or_lock_mobile(self):
        self.assert_error(*self.request("POST", "/api/auth/forgot-password", {"mobile": self.mobile}, cookie=""), 403)
        self.assertEqual(self.request("POST", "/api/auth/forgot-password", {"mobile": self.mobile})[0], 200)

    def test_auth_expired_code_and_revoked_browser_rejected(self):
        status, challenge = self.request("POST", "/api/auth/forgot-password", {"mobile": self.mobile})
        self.assertEqual(status, 200)
        payload = {"mobile": self.mobile, "challenge_id": challenge["challenge_id"], "otp": challenge["demo_otp"], "password": "New canteen password"}
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE password_reset_challenges SET expires_at=0 WHERE id=?", (payload["challenge_id"],))
        self.assert_error(*self.request("POST", "/api/auth/reset-password", payload), 400)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE password_reset_challenges SET expires_at=? WHERE id=?", (int(time.time()) + 600, payload["challenge_id"]))
            conn.execute("DELETE FROM demo_recovery_devices WHERE account_id=?", (self.account["id"],))
        self.assert_error(*self.request("POST", "/api/auth/reset-password", payload), 400)

    def test_auth_otp_attempt_limit_and_resend_cooldown(self):
        status, challenge = self.request("POST", "/api/auth/forgot-password", {"mobile": self.mobile})
        self.assertEqual(status, 200)
        self.assert_error(*self.request("POST", "/api/auth/forgot-password", {"mobile": self.mobile}), 429)
        wrong = "000000" if challenge["demo_otp"] != "000000" else "111111"
        payload = {"mobile": self.mobile, "challenge_id": challenge["challenge_id"], "otp": wrong, "password": "New canteen password"}
        for _ in range(5):
            self.assert_error(*self.request("POST", "/api/auth/reset-password", payload), 400)
        self.assert_error(*self.request("POST", "/api/auth/reset-password", dict(payload, otp=challenge["demo_otp"])), 400)

    def test_health(self):
        status, data = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])

    def test_multi_item_bill_stock_history_and_sales(self):
        meal = self.item(price=4575, stock=10)
        drink = self.item("Lime juice", price=1250, stock=8)
        payload = self.order((meal["id"], 2), (drink["id"], 3))
        # Untrusted client totals must never affect the calculated bill.
        payload["total_paise"] = 1
        status, data = self.request("POST", "/api/orders", payload)
        self.assertIn(status, (200, 201), data)
        self.assertEqual(data["order"]["total_paise"], 12900)
        self.assertEqual(data["order"]["is_demo"], 0)
        self.assertEqual(self.stock(meal["id"]), 8)
        self.assertEqual(self.stock(drink["id"]), 5)
        status, history = self.request("GET", "/api/orders")
        self.assertEqual(status, 200)
        stored = next(row for row in history["orders"] if row["id"] == payload["id"])
        self.assertEqual(len(stored["items"]), 2)
        self.assertEqual(stored["total_paise"], 12900)
        status, sales = self.request("GET", "/api/sales")
        self.assertEqual(status, 200)
        lines = [row for row in sales["lines"] if row["order_id"] == payload["id"]]
        self.assertEqual(len(lines), 2)
        self.assertEqual(sum(row["line_total_paise"] for row in lines), 12900)

    def test_duplicate_items_aggregate_before_stock_check(self):
        item = self.item(stock=5)
        payload = self.order((item["id"], 2), (item["id"], 3))
        status, data = self.request("POST", "/api/orders", payload)
        self.assertIn(status, (200, 201), data)
        self.assertEqual(self.stock(item["id"]), 0)
        self.assertEqual(len(data["order"]["items"]), 1)
        self.assertEqual(data["order"]["items"][0]["quantity"], 5)

    def test_insufficient_stock_rolls_back_entire_order(self):
        first = self.item(stock=10)
        second = self.item(stock=1)
        payload = self.order((first["id"], 3), (second["id"], 2))
        status, data = self.request("POST", "/api/orders", payload)
        self.assert_error(status, data, 409)
        self.assertEqual(self.stock(first["id"]), 10)
        self.assertEqual(self.stock(second["id"]), 1)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM orders WHERE id=?", (payload["id"],)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM order_items WHERE order_id=?", (payload["id"],)).fetchone()[0], 0)

    def test_duplicate_total_cannot_oversell(self):
        item = self.item(stock=3)
        status, data = self.request("POST", "/api/orders", self.order((item["id"], 2), (item["id"], 2)))
        self.assert_error(status, data, 409)
        self.assertEqual(self.stock(item["id"]), 3)

    def test_idempotency_returns_same_order_without_second_stock_decrement(self):
        item = self.item(stock=4)
        payload = self.order((item["id"], 2))
        status, original = self.request("POST", "/api/orders", payload)
        self.assertIn(status, (200, 201), original)
        status, retried = self.request("POST", "/api/orders", payload)
        self.assertIn(status, (200, 201), retried)
        self.assertEqual(retried["order"], original["order"])
        self.assertEqual(self.stock(item["id"]), 2)
        changed = dict(payload, customer_name="Different Student")
        status, data = self.request("POST", "/api/orders", changed)
        self.assert_error(status, data, 409)
        self.assertEqual(self.stock(item["id"]), 2)

    def test_concurrent_orders_cannot_sell_last_item_twice(self):
        item = self.item(stock=1)
        barrier = threading.Barrier(2)
        def buy():
            barrier.wait(timeout=5)
            return self.request("POST", "/api/orders", self.order((item["id"], 1)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: buy(), range(2)))
        self.assertEqual(sum(status in (200, 201) for status, _ in results), 1, results)
        self.assertEqual(sum(status == 409 for status, _ in results), 1, results)
        self.assertEqual(self.stock(item["id"]), 0)

    def test_invalid_order_and_malformed_json_rejected(self):
        item = self.item(stock=5)
        cases = [
            self.order(),
            self.order((item["id"], 0)),
            self.order((item["id"], -1)),
            self.order((item["id"], 1.5)),
            self.order((item["id"], "2")),
            self.order((item["id"], 1), payment_method="Crypto"),
            self.order((item["id"], 1), order_type="Delivery"),
            self.order((item["id"], 1), id="not-a-uuid"),
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                status, data = self.request("POST", "/api/orders", payload)
                self.assert_error(status, data, 400)
        status, data = self.request("POST", "/api/orders", raw=b'{"items":')
        self.assert_error(status, data, 400)
        self.assertEqual(self.stock(item["id"]), 5)

    def test_menu_validation_and_deactivation(self):
        item = self.item(stock=3)
        for changes in ({"price_paise": 0}, {"price_paise": 10.5}, {"stock": -1}, {"stock": "4"}, {"name": ""}):
            with self.subTest(changes=changes):
                status, data = self.request("PATCH", f'/api/menu/{item["id"]}', dict(item, **changes))
                self.assert_error(status, data, 400)
        status, data = self.request("PATCH", f'/api/menu/{item["id"]}', dict(item, stock=7, active=0))
        self.assertEqual(status, 200, data)
        self.assertEqual(data["item"]["stock"], 7)
        self.assertEqual(data["item"]["active"], 0)
        status, data = self.request("POST", "/api/orders", self.order((item["id"], 1)))
        self.assertIn(status, (400, 404, 409), data)
        self.assertEqual(self.stock(item["id"]), 7)

    def test_unknown_item_rejected(self):
        payload = self.order((2147483647, 1))
        status, data = self.request("POST", "/api/orders", payload)
        self.assertIn(status, (400, 404), data)
        self.assertIsInstance(data.get("error"), str)

    def test_cross_origin_write_rejected_and_same_origin_accepted(self):
        item = self.item(stock=2)
        payload = self.order((item["id"], 1))
        status, data = self.request("POST", "/api/orders", payload, origin="https://untrusted.example")
        self.assertIn(status, (400, 403), data)
        self.assertEqual(self.stock(item["id"]), 2)
        status, data = self.request("POST", "/api/orders", payload, origin=self.base)
        self.assertIn(status, (200, 201), data)
        self.assertEqual(self.stock(item["id"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
