#!/usr/bin/env bash
# Run from the project root with java/run.sh running. Supply a curl cookie jar
# from an authenticated session using CANTEEN_COOKIE_JAR; never commit that file.
set -euo pipefail
: "${CANTEEN_COOKIE_JAR:?Set CANTEEN_COOKIE_JAR to your private authenticated curl cookie-jar path}"
curl --fail-with-body --silent --show-error -b "$CANTEEN_COOKIE_JAR" http://127.0.0.1:8080/api/menu
# Use current item IDs returned by your account menu in a private request file.
: "${CANTEEN_ORDER_FILE:?Set CANTEEN_ORDER_FILE to an order JSON file with your account item IDs}"
curl --fail-with-body --silent --show-error -b "$CANTEEN_COOKIE_JAR" http://127.0.0.1:8080/api/orders \
  -H 'Content-Type: application/json' --data-binary "@$CANTEEN_ORDER_FILE"
curl --fail-with-body --silent --show-error -b "$CANTEEN_COOKIE_JAR" http://127.0.0.1:8080/api/sales
