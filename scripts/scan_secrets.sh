#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

fail=0

while IFS= read -r f; do
  [ -z "$f" ] && continue
  base=$(basename "$f")
  case "$base" in
    .env.example) ;;
    .env|.env.*|env|env.*|*.env|*.db|*.sqlite|*.sqlite3|*.eml|*.pem|*.key)
      echo "forbidden file: $f"
      fail=1
      ;;
  esac
done < <( { git ls-files; git diff --cached --name-only --diff-filter=AM; } | sort -u)

pattern='(hk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'

hits=$( { git grep -I -n -E "$pattern" -- . ':!scripts/scan_secrets.sh' 2>/dev/null || true
          git grep --cached -I -n -E "$pattern" -- . ':!scripts/scan_secrets.sh' 2>/dev/null || true; } | sort -u)

if [ -n "$hits" ]; then
  echo "$hits" | sed -E 's/(hk_|sk-|gh[pousr]_|github_pat_|AKIA)([A-Za-z0-9_-]{4})[A-Za-z0-9_-]+/\1\2...REDACTED/g'
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "Secret scan failed, do not push."
  exit 1
fi
echo "Secret scan clean."
