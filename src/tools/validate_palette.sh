#!/bin/zsh
# Validate a categorical chart palette with the dataviz validator, run through headless Chrome
# (no Node needed). Usage: tools/validate_palette.sh "#hex,#hex,..." dark|light "#surface" [adjacent|all]
set -e
P="$1"; M="${2:-dark}"; S="${3:-#1B1F3B}"; PR="${4:-adjacent}"
HERE="$(cd "$(dirname "$0")" && pwd)"
VAL="$HERE/validate_palette.js"
if [ ! -f "$VAL" ]; then
  echo "validate_palette.js not found next to this script; copy it from the dataviz skill (scripts/validate_palette.js)." >&2
  exit 2
fi
TMP="$(mktemp -d)"
cp "$VAL" "$TMP/validate_palette.js"
cat > "$TMP/t.html" <<HTML
<!doctype html><html><body>
<script type="module">
import * as V from './validate_palette.js';
const r = V.validate("$P".split(","), {mode:"$M", surface:"$S", pairs:"$PR"});
for (const [name,state,detail] of r.report) console.log("ROW|"+name+"|"+state+"|"+detail);
console.log("OK|"+r.ok);
</script>
</body></html>
HTML
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless=new --disable-gpu --no-sandbox --allow-file-access-from-files \
  --enable-logging=stderr --v=0 --virtual-time-budget=3000 --dump-dom "file://$TMP/t.html" 2>&1 >/dev/null \
  | grep -E 'CONSOLE' | sed -E 's/.*CONSOLE[^"]*"//; s/", source:.*//'
rm -rf "$TMP"
