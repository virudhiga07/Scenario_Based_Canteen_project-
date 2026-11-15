#!/usr/bin/env bash
set -euo pipefail
CANTEEN_JAVA_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$CANTEEN_JAVA_DIR"
mkdir -p lib build
while IFS=$'\t' read -r filename artifact expected; do
  if [[ ! -f "lib/$filename" ]]; then
    curl --fail --location --retry 2 --silent --show-error "https://repo.maven.apache.org/maven2/$artifact" -o "lib/$filename.download"
    mv "lib/$filename.download" "lib/$filename"
  fi
  actual="$(sha256sum "lib/$filename" | cut -d ' ' -f 1)"
  [[ "$actual" == "$expected" ]] || { echo "Checksum mismatch: $filename" >&2; exit 1; }
done < dependencies.tsv
CANTEEN_CLASSPATH="$(printf '%s:' lib/*.jar)"
if command -v javac >/dev/null 2>&1; then
  javac --release 17 -cp "$CANTEEN_CLASSPATH" -d build src/*.java
else
  java -m jdk.compiler/com.sun.tools.javac.Main -source 17 -target 17 -cp "$CANTEEN_CLASSPATH" -d build src/*.java
fi
