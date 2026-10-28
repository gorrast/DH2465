// Run with: node tools/test-youtube-import.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const { File } = require('node:buffer');
const { spawnSync } = require('node:child_process');
const output = { exports: {} };
vm.runInNewContext(ts.transpileModule(fs.readFileSync('lib/youtube-import.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { exports: output.exports, File, URL, TextEncoder });
const { prepareYoutubeImport, YOUTUBE_UPLOAD_BYTES } = output.exports;
const now = Date.parse('2026-10-28T12:00:00Z');
const video = (days, title = 'Watched Example') => ({
  title, titleUrl: 'https://www.youtube.com/watch?v=abcdefghijk&tracking=unused',
  time: new Date(now - days * 86_400_000).toISOString(),
  subtitles: [{ name: 'Example channel', url: 'https://unused.example' }],
  description: 'unused metadata '.repeat(1500), products: ['YouTube'],
});
const file = (rows, name = 'watch-history.json') => new File([JSON.stringify(rows, null, 2)], name);

(async () => {
  const recent = video(1);
  const ad = { ...video(0), details: [{ name: 'Från en annons på Google' }] };
  const unavailable = { title: 'Watched unavailable video', time: recent.time };
  const original = file([recent, video(60), video(120), ad, unavailable,
    { ...video(0), titleUrl: 'https://www.youtube.com/results?search_query=test' }]);
  const prepared = await prepareYoutubeImport([original, file([recent])], '90', now);
  const rows = JSON.parse(await prepared.file.text());
  assert.equal(rows.length, 3);
  assert.equal(prepared.skipped, 1);
  assert(prepared.file.size < original.size / 10);
  assert.equal(rows[0].subtitles[0].name, 'Example channel');
  assert.equal(rows[0].titleUrl, 'https://www.youtube.com/watch?v=abcdefghijk');
  assert(!('description' in rows[0]));
  assert.equal(JSON.parse(await original.text()).length, 6);
  assert.equal(JSON.parse(await (await prepareYoutubeImport([original], '30', now)).file.text()).length, 2);
  assert.equal(JSON.parse(await (await prepareYoutubeImport([original], 'all', now)).file.text()).length, 4);
  const capped = await prepareYoutubeImport([file(Array.from({ length: 5010 }, (_, i) => ({ ...video(1, `Watched ${i}`), description: undefined })))], 'all', now);
  assert.equal(JSON.parse(await capped.file.text()).length, 5000);
  assert.equal(capped.skipped, 10);
  // UTF-8 byte counting and multipart overhead, even with unusually long titles.
  const large = await prepareYoutubeImport([file(Array.from({ length: 100 }, (_, i) => ({ ...video(i / 100, `Watched ${i} ${'🌙'.repeat(20_000)}`), description: undefined })))], 'all', now);
  assert(large.file.size <= YOUTUBE_UPLOAD_BYTES);
  assert(large.sizeLimited);
  assert.equal(JSON.parse(await large.file.text())[0].time, new Date(now).toISOString());
  await assert.rejects(prepareYoutubeImport([file([video(120)])], '30', now), /No YouTube viewing entries/);
  await assert.rejects(prepareYoutubeImport([new File(['{bad'], 'broken.json')], '90', now), /valid Google Takeout/);
  await assert.rejects(prepareYoutubeImport([file({})], '90', now), /watch-history.json array/);
  await assert.rejects(prepareYoutubeImport([file([{ ...recent, time: 'bad' }])], '90', now), /invalid timestamp/);
  // Send the compact output through the actual Python parser to catch format drift.
  const python = process.env.PYTHON || (fs.existsSync('.venv/bin/python') ? '.venv/bin/python' : 'python3');
  const parsed = spawnSync(python, ['-c',
    'import sys,json; from stressless.connectors.media import parse_media; rows=parse_media("youtube","watch-history.json",sys.stdin.buffer.read()); assert len(rows)==3; assert rows[0]["creator"]=="Example channel"; assert rows[0]["source"]["video_id"]=="abcdefghijk"; print("Backend parser accepts compact export")'],
    { input: await prepared.file.text(), encoding: 'utf8', timeout: 10_000, env: { ...process.env, PYTHONPATH: 'backend' } });
  assert.equal(parsed.status, 0, parsed.stderr || String(parsed.error));
  console.log(parsed.stdout.trim());
  console.log('PASS: date ranges, ads/search exclusion, unavailable videos, deduplication, entry/byte limits, malformed files, and original file preservation');
})().catch((error) => { console.error(error); process.exitCode = 1; });
