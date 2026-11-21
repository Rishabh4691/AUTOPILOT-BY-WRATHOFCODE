#!/usr/bin/env bash
# Fails if anything staged or tracked looks like a secret. Run before every push.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

fail=0
# 1. forbidden files
for f in $(git ls-files --cached; git diff --cached --name-only); do
  case "$f" in
    .env|.env.*) [ "$f" = ".env.example" ] || { echo "FORBIDDEN FILE: $f"; fail=1; } ;;
    *.db|*.sqlite|*.eml|*.pem|*.key) echo "FORBIDDEN FILE: $f"; fail=1 ;;
  esac
done

# 2. secret-looking strings in tracked + staged content
pattern='(hk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
if git grep -I -n -E "$pattern" -- . ':!scripts/scan_secrets.sh' 2>/dev/null; then fail=1; fi
if git grep --cached -I -n -E "$pattern" -- . ':!scripts/scan_secrets.sh' 2>/dev/null; then fail=1; fi

if [ "$fail" -ne 0 ]; then echo "❌ Secret scan FAILED — do not push."; exit 1; fi
echo "✅ Secret scan clean."
