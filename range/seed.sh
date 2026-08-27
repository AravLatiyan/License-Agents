#!/usr/bin/env bash
set -euo pipefail

MAILPIT_URL="${MAILPIT_URL:-http://localhost:8025}"
FIXTURES_DIR="${FIXTURES_DIR:-$(dirname "$0")/fixtures}"

count=0

for fixture in \
  "$FIXTURES_DIR"/malicious/*.json \
  "$FIXTURES_DIR"/legitimate/*.json
do
  [ -f "$fixture" ] || continue

  curl -fsS -X POST "${MAILPIT_URL}/api/v1/send" \
    -H "Content-Type: application/json" \
    --data-binary "@${fixture}" \
    >/dev/null
  count=$((count + 1))
  echo "Seeded $(basename "$fixture")"
done

echo "Seeded ${count} Range fixtures into Mailpit."