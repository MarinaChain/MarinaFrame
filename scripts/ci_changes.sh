#!/usr/bin/env bash
# Read NUL-delimited paths from git diff --name-only --no-renames -z.
set -euo pipefail
python=false
rust=false
ui=false
wheel=false
while IFS= read -r -d '' path; do
  case "$path" in
    .github/workflows/*|*.lock|*/Cargo.toml|Cargo.toml|*/package.json|package.json|*/package-lock.json|package-lock.json|*/pyproject.toml|pyproject.toml|requirements*.txt|rust-toolchain.toml|Makefile)
      python=true; rust=true; ui=true; wheel=true ;;
    docs/*|*.md|tasks/*|work/pm-briefs/*) ;;
    app/ui/*|app/ui-tests/*) ui=true ;;
    crates/*|app/core/*|app/src-tauri/*) rust=true; wheel=true ;;
    src/*|tests/*|examples/*)
      # Rust integration tests and installed-wheel smoke invoke Python workers.
      python=true; rust=true; wheel=true ;;
    *) python=true; rust=true; ui=true; wheel=true ;;
  esac
done
printf 'python=%s\nrust=%s\nui=%s\nwheel=%s\n' "$python" "$rust" "$ui" "$wheel"
