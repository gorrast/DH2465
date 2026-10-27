# Media brand marks

Spotify, Netflix, YouTube and Steam SVG marks are bundled from the Simple Icons project:
https://github.com/simple-icons/simple-icons/tree/develop/icons

The Simple Icons license is included in `simple-icons-LICENSE.md`. Brand names and marks belong to their
respective owners. These local vector files are used as decorative CSS masks in the Media page's hero;
no remote image service, API key or PNG upload is required.

The TMDB mark is also supplied by Simple Icons and is displayed in the Netflix metadata credits in unchanged
monochrome form. TMDB catalogue posters require a server-side API Read Access Token, as described in README.

The Weekly heading also uses locally bundled Simple Icons marks for Instagram, TikTok, Discord,
Reddit, WhatsApp, Snapchat, Google Chrome, and Facebook, alongside the existing media marks.
Package IDs are mapped in `lib/app-brands.ts`; unknown apps use initials. Apps from the user's
app-usage and app heart-rate rankings appear in the decorative row. When neither ranking has data,
a labeled set of seven illustrative app logos is displayed instead; no statistics are fabricated.
