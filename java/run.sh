#!/usr/bin/env bash
set -euo pipefail
CANTEEN_JAVA_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$CANTEEN_JAVA_DIR/build.sh"
exec java -cp "$CANTEEN_JAVA_DIR/build:$CANTEEN_JAVA_DIR/lib/*" CanteenServer --root "$(dirname "$CANTEEN_JAVA_DIR")" "$@"
