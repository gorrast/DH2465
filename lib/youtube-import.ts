type WatchEntry = { title: string; titleUrl?: string; time: string; subtitles?: { name: string }[] };
type HistoryRange = '30' | '90' | 'all';

// Leave room for multipart boundaries below Vercel's 4.5 MB request limit.
export const YOUTUBE_UPLOAD_BYTES = 4_000_000;
const adMarkers = new Set(['from google ads', 'from a google ad', 'från en annons på google']);

/** Keep only the fields consumed by our Takeout parser; original files stay local. */
export async function prepareYoutubeImport(files: File[], range: HistoryRange, now = Date.now()) {
  if (files.length > 20) throw new Error('Choose no more than 20 history files at a time.');
  const cutoff = range === 'all' ? -Infinity : now - Number(range) * 86_400_000;
  const entries: { entry: WatchEntry; timestamp: number }[] = [];
  const seen = new Set<string>();
  let available = 0;
  for (const file of files) {
    let data: unknown;
    try { data = JSON.parse((await file.text()).replace(/^\uFEFF/, '')); }
    catch { throw new Error(`${file.name}: choose a valid Google Takeout watch-history JSON file.`); }
    if (!Array.isArray(data)) throw new Error(`${file.name}: choose the watch-history.json array from Google Takeout.`);
    for (const item of data) {
      if (!item || typeof item !== 'object' || Array.isArray(item)) continue;
      if (Array.isArray(item.details) && item.details.some((part: { name?: unknown } | null) =>
        part && adMarkers.has(String(part.name || '').trim().toLowerCase()))) continue;
      const rawUrl = String(item.titleUrl || '');
      const title = String(item.title || '').trim();
      let videoId = '';
      try {
        const url = new URL(rawUrl);
        if (url.protocol === 'https:' && ['www.youtube.com', 'youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'].includes(url.hostname)) {
          videoId = url.hostname === 'youtu.be' ? url.pathname.replace(/^\/+|\/+$/g, '')
            : url.pathname === '/watch' ? url.searchParams.get('v') || ''
            : url.pathname.startsWith('/shorts/') ? url.pathname.split('/')[2] : '';
        }
      } catch { /* Takeout can contain unavailable videos without a URL. */ }
      if (!/^[A-Za-z0-9_-]{11}$/.test(videoId)) videoId = '';
      if (!videoId && !(!rawUrl && /^(Watched |Tittade på )/.test(title))) continue;
      const timestamp = typeof item.time === 'string' ? Date.parse(item.time) : NaN;
      if (!Number.isFinite(timestamp)) throw new Error(`${file.name}: a viewing entry has an invalid timestamp. Your saved history is unchanged.`);
      const channel = Array.isArray(item.subtitles) ? item.subtitles.find((part: unknown) => part && typeof part === 'object' && !Array.isArray(part)) : undefined;
      const creator = String(channel?.name || '');
      const time = new Date(timestamp).toISOString();
      const key = JSON.stringify([time, title.replace(/^(?:Watched|Tittade på)\s+/, '').trim() || 'Video unavailable', creator, videoId]);
      if (seen.has(key)) continue;
      seen.add(key);
      available++;
      if (timestamp < cutoff) continue;
      entries.push({ timestamp, entry: { title, time, ...(videoId ? { titleUrl: 'https://www.youtube.com/watch?v=' + videoId } : {}), ...(creator ? { subtitles: [{ name: creator }] } : {}) } });
    }
  }
  entries.sort((a, b) => b.timestamp - a.timestamp);
  const selected = entries.slice(0, 5000);
  const encoder = new TextEncoder();
  const parts: string[] = [];
  let bytes = 2; // JSON array brackets
  for (const { entry } of selected) {
    const part = JSON.stringify(entry);
    const size = encoder.encode(part).length + (parts.length ? 1 : 0);
    if (bytes + size > YOUTUBE_UPLOAD_BYTES) break;
    parts.push(part);
    bytes += size;
  }
  if (!parts.length) throw new Error(entries.length
    ? 'A viewing entry is too large to upload. Choose another history export.'
    : 'No YouTube viewing entries in the selected period. Choose a wider range; your saved history is unchanged.');
  return {
    file: new File(['[' + parts.join(',') + ']'], 'watch-history.json', { type: 'application/json' }),
    skipped: available - parts.length,
    sizeLimited: parts.length < selected.length,
  };
}
