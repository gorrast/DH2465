#!/usr/bin/env bash
# Prints one SQL script for the Supabase SQL editor: every migration in order, then supabase/tests/schema_checks.sql,
# all in one transaction that ends in an error, so nothing is ever committed. Success is the final error
# "ALL SCHEMA CHECKS PASSED"; any other error names the failing check.
#
#   tools/schema_rollback_test.sh > /tmp/schema_test.sql    # then paste the file into the SQL editor
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"

echo "begin;"
# If the editor ever ran statements one by one (autocommit), this table would be gone by the next statement and the
# script would stop here, before any migration.
echo "create temp table rollback_guard (ok int) on commit drop;"
echo "insert into rollback_guard values (1);"
for f in "$root"/supabase/migrations/*.sql; do
  printf '\n-- ===== %s\n' "$(basename "$f")"
  cat "$f"
done
printf '\n-- ===== schema_checks.sql\n'
cat "$root/supabase/tests/schema_checks.sql"
