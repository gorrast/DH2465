// Teaches capacitor-health-connect@0.7 to return HeartRateVariabilityRmssd records.
// The plugin already resolves the record type and its permission (READ_HEART_RATE_VARIABILITY) through Health
// Connect's own name map, but its serializer only knows a fixed list of record classes and throws on anything else.
// Runs on postinstall; safe to run again.
const fs = require("fs");
const path = require("path");

const file = path.join(
  __dirname,
  "..",
  "node_modules/capacitor-health-connect/android/src/main/java/com/ubiehealth/capacitor/healthconnect/Serializer.kt"
);
const MARK = "is HeartRateVariabilityRmssdRecord ->";
const ANCHOR = /^( *)is HeightRecord -> \{/m;

if (!fs.existsSync(file)) {
  console.log("patch-health-connect: plugin not installed, skipped");
  process.exit(0);
}
const src = fs.readFileSync(file, "utf8");
if (src.includes(MARK)) {
  console.log("patch-health-connect: already patched");
  process.exit(0);
}
const m = ANCHOR.exec(src);
if (!m) {
  console.error("patch-health-connect: HeightRecord case not found; the plugin changed, update this script");
  process.exit(1);
}
const nl = src.includes("\r\n") ? "\r\n" : "\n";
const pad = m[1];
const block = [
  `${pad}${MARK} {`,
  `${pad}    obj.put("time", this.time)`,
  `${pad}    obj.put("zoneOffset", this.zoneOffset?.toJSONValue())`,
  `${pad}    obj.put("heartRateVariabilityMillis", this.heartRateVariabilityMillis)`,
  `${pad}}`,
  "",
].join(nl);
fs.writeFileSync(file, src.slice(0, m.index) + block + src.slice(m.index));
console.log("patch-health-connect: added HeartRateVariabilityRmssdRecord");
