export type AppIdentity = { packageName: string; appName: string };
export type AppBrand = { key: string; name: string; logo?: string; color: string; initials: string };

type BrandDefinition = { key: string; name: string; color: string; packages: string[]; aliases?: string[] };
const BRANDS: BrandDefinition[] = [
  { key: 'spotify', name: 'Spotify', color: '#1ed760', packages: ['com.spotify.music', 'com.spotify.lite'], aliases: ['spotify'] },
  { key: 'youtube', name: 'YouTube', color: '#ff5a63', packages: ['com.google.android.youtube', 'com.google.android.apps.youtube.music', 'com.youtube'], aliases: ['youtube', 'youtube music'] },
  { key: 'netflix', name: 'Netflix', color: '#ed4254', packages: ['com.netflix.mediaclient'], aliases: ['netflix'] },
  { key: 'steam', name: 'Steam', color: '#85afd9', packages: ['com.valvesoftware.android.steam.community', 'com.valvesoftware.android.steam.friendsui'], aliases: ['steam', 'steam chat'] },
  { key: 'instagram', name: 'Instagram', color: '#e972ac', packages: ['com.instagram.android', 'com.instagram.lite'], aliases: ['instagram'] },
  { key: 'tiktok', name: 'TikTok', color: '#60d6df', packages: ['com.zhiliaoapp.musically', 'com.ss.android.ugc.trill', 'com.zhiliaoapp.musically.go'], aliases: ['tiktok', 'tik tok'] },
  { key: 'discord', name: 'Discord', color: '#9b9ff3', packages: ['com.discord'], aliases: ['discord'] },
  { key: 'reddit', name: 'Reddit', color: '#ff815c', packages: ['com.reddit.frontpage'], aliases: ['reddit'] },
  { key: 'whatsapp', name: 'WhatsApp', color: '#64d98c', packages: ['com.whatsapp', 'com.whatsapp.w4b'], aliases: ['whatsapp', 'whatsapp business'] },
  { key: 'snapchat', name: 'Snapchat', color: '#f4de67', packages: ['com.snapchat.android'], aliases: ['snapchat'] },
  { key: 'googlechrome', name: 'Chrome', color: '#8ac7ef', packages: ['com.android.chrome', 'com.chrome.beta', 'com.chrome.dev', 'com.chrome.canary'], aliases: ['chrome', 'google chrome'] },
  { key: 'facebook', name: 'Facebook', color: '#78adf7', packages: ['com.facebook.katana', 'com.facebook.lite'], aliases: ['facebook'] },
];

export function appBrand(app: AppIdentity): AppBrand {
  const packageName = app.packageName.trim().toLowerCase();
  const name = app.appName.trim();
  const match = BRANDS.find(brand => brand.packages.includes(packageName) || brand.aliases?.includes(name.toLowerCase()));
  const label = match?.name || name || packageName;
  const words = label.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  const initials = words.length > 1 ? words.slice(0, 2).map(word => word[0]).join('') : label.slice(0, 2);
  return {
    key: match?.key || packageName || label.toLowerCase(), name: label,
    logo: match ? '/brands/' + match.key + '.svg' : undefined,
    color: match?.color || '#b29bda', initials: initials.toUpperCase(),
  };
}

/** Alternate the two rankings, keep one mark per app, and never invent connected apps. */
export function featuredAppBrands(usage: AppIdentity[], response: AppIdentity[], limit = 7): AppBrand[] {
  const brands = new Map<string, AppBrand>();
  for (let i = 0; i < Math.max(usage.length, response.length) && brands.size < limit; i++) {
    for (const app of [usage[i], response[i]]) {
      if (!app || brands.size >= limit) continue;
      const brand = appBrand(app);
      if (!brands.has(brand.key)) brands.set(brand.key, brand);
    }
  }
  return [...brands.values()];
}

/** Illustrative defaults for an empty account; these do not represent a usage ranking. */
export const EXAMPLE_APP_BRANDS: AppBrand[] = [
  'Spotify', 'YouTube', 'WhatsApp', 'Instagram', 'TikTok', 'Facebook', 'Snapchat',
].map(appName => appBrand({ packageName: '', appName }));
