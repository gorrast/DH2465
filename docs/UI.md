# UI implementation

## Architecture

The application uses React, CSS tokens and SVG charts without additional UI runtime dependencies. `styles/base.css` owns shared layout and controls. View styles live in `styles/views/`. `design.md` specifies the target system.

Today implements After Hours: self-hosted Manrope/Newsreader, navy/cream surfaces, an illuminated sleep score, evidence-linked timeline inspection, guarded save/export and readable evidence/stage tables. All pages share the navy/cream surfaces and Manrope/Newsreader typography. Other views retain their layouts and semantic colours; page headings, Replay’s metric panel and Planner’s estimate panel use the shared report glow. Font licences are retained in `public/fonts`; public fonts bypass authentication middleware, while application routes remain protected.

Theme precedence is explicit `?theme=light|dark`, saved preference, then dark. Saving a suggestion stores a StressLess plan block; `.ics` export creates a calendar file. Neither operation implies a calendar-service write. Forecast ranges express uncertainty.

Controls use a shared purple interaction palette, independent of chart/status colours. Native disclosures retain keyboard and expanded-state semantics; Explore the demo includes a reserved CSS chevron and indented destinations. All routes use the shared sidebar style and coral brand mark.

## Verification

Run `npm run dev` for the application and API. Run `npm run typecheck` and `npm run build` before delivery. Against a running instance and confirmed test account:

```bash
STRESSLESS_EMAIL=… STRESSLESS_PASSWORD=… npm run screenshots -- --theme light --out /tmp/stressless-desktop
STRESSLESS_EMAIL=… STRESSLESS_PASSWORD=… npm run screenshots -- --theme dark --mobile --out /tmp/stressless-mobile
```

The 21 October 2026 Today checks used an isolated in-memory API: desktop, 390px/320px phones, both themes, save failure/retry/success, keyboard evidence/slider access, missing watch data, insufficient history and night details. These results concern that implementation; subsequent changes require appropriate verification. Temporary preview routes and test APIs are excluded from production.

Today uses a two-column headline/score opening, a larger night date above it and separate scroll-entry sections. Rating, baseline and sleep facts occupy a larger summary section before the protected-space action. The navigation trigger shows Menu and a hover/click hint. The ring and halo breathe over ten seconds; the value remains steady. Pause and reduced motion stop the loop. Desktop navigation reveals on hover or toggle, with inert closed content and Escape focus return. Light mode uses warm cream surfaces.

Browser verification of the score-focused layout used intercepted simulated responses: desktop/tablet and 390px/320px widths, both themes, no page overflow, hover/toggle navigation, Escape focus return, dropdown indicator, section/evidence disclosure, pause and reduced motion. The temporary preview route was removed after verification.

Findings deduplicate repeated detail/evidence sentences while preserving charts. Duration comparisons use larger text and green/red higher/lower values. A shared renderer and palette colour signed point changes across views, tables, chart labels and tooltips; zero and unavailable values stay neutral. The larger sunrise-red/peach glow shares the ring’s ten-second breathing cycle, pause and reduced-motion behaviour. The gradient and ring animate on bounded compositor layers; the numeric readout remains static. Chromium reported three accelerated layers and zero layer-paint events during a 2.2 s steady-state sample. Browser checks cover both signs, neutral values and phone reflow.

Motion coordinates evidence height/opacity (480 ms), once-only section entry (1000 ms), a damped navigation spring, cursor-glow spring values and planner layout changes (600 ms). Closed disclosures and navigation are inert. Reduced motion removes these transitions; the login pause control resets pointer tracking. Browser checks cover interruption, Escape/focus return, planner changes, pointer pause and mobile overflow.

Login reveals two lines over 1450 ms with 24px movement. Today’s stronger background glow scales to 1.28 and fades to 0.15 over an extended scroll range; pause and reduced motion restore a static glow. Primary actions scale to 1.035 on hover and .965 on press over 260 ms. Sidebar links and recovery markers use 110 ms stagger, with 450/650 ms item transitions. Newly added planner cards and saved confirmations fade in without replaying existing card entrances. These effects use the core Motion package.

Login and Today share one headline-reveal component: 1200 ms opacity/24px entrance with a 250 ms line offset. Today includes the hero, section headings, action titles and expanded sleep-stage heading. Each runs once on viewport entry; pause and reduced motion show the final state without replay.

Today uses native proximity scroll snapping at stable section boundaries, with sticky-header and phone-navigation clearance. Long sections retain free scrolling. Pause motion and reduced motion disable snapping; other pages are unaffected.

Media now uses a journal opening and three separate listening, watching and playing sections, sharing
Newsreader/Manrope, section and heading reveals, native proximity snapping, and pause/reduced-motion
support with Morning. Histories scroll independently and load additional records per provider. Steam
snapshots have local library search/sort; Spotify export summaries remain available in disclosures.
The view no longer requests media insights or health/calendar correlations. Imports do not call the
statistical engine or Claude. Netflix viewing dates remain date-only and absent duration stays unavailable.

Media browser checks used an isolated preview with intercepted API responses: 1440px dark/light,
390px dark and 320px light; no horizontal overflow; history pagination, two-file Netflix selection,
Steam search/sort, motion controls, empty states and upload failure/retry/success/input reset passed.
Both supplied Netflix exports also passed an isolated API import with 6,536 rows, including eight
unavailable titles and same-day rewatches, while an engine-session guard asserted no engine calls.
The temporary preview route and personal data fixtures are excluded from production.

Steam also has a server-backed Sync now action, setup/account details, busy and error states, and a persisted
last-synced timestamp. Personal server configuration binds the Steam account to a Supabase Auth user UUID;
the key is only sent in a Steam request header. Sync and file import disable each other while running.
Mocked browser checks at 1440px dark, 390px light and 320px dark cover pending controls, failure preserving the
library, retry/success refreshing games and timestamp, missing configuration, and no horizontal overflow.
Live Steam credentials are required to verify an actual account; no scheduled polling is enabled.

Last.fm now has a separate listening panel below Spotify imports, with a featured latest listen, album-cover
thumbnails, profile/catalogue attribution links, Sync now, resumable new-listening catch-up and older-history
backfill. Scrobbles retain timestamps and explicitly unavailable playback duration; their counts are kept
separate from Spotify exports. Recent-track image URLs are used first; missing or broken covers trigger a
paced, cached album-metadata lookup only when visible, then fall back to a music icon. No shared secret,
callback, Claude call, statistical-engine call or scheduled polling is used.

Live read-only Last.fm checks with the configured account returned 200 completed scrobbles, 187 usable
artwork URLs and additional history. Real covers rendered in isolated browser fixtures at 1440px dark,
390px light and 320px dark, with no horizontal overflow. Checks also passed sync failure/retry, busy controls,
catch-up/backfill, saved-history pagination and album-artwork fallback. Personal fixtures and the temporary
preview route are excluded from production. The Last.fm migration still needs applying to the remote database.

The Media hero includes twelve staggered Spotify, Netflix and Steam logo bubbles behind the headline.
Local Simple Icons SVG marks act as CSS masks; 29–40 second transform/opacity loops rise and drift within
the clipped hero. Pause motion freezes the bubbles in place, while reduced motion presents static marks.
The decorative layer is hidden from assistive technology and cannot intercept clicks. Browser checks passed
at 1440px dark, 390px dark and 320px light, plus 1440px light with reduced motion: all local SVGs loaded,
pause/resume and static reduced motion worked, and there was no horizontal overflow. No PNG setup is needed.

Steam game cards display official header images attached during sync/import, with gamepad placeholders for
missing/removed images. Netflix imports attach catalogue lookup keys and automatically run bounded poster
batches after the history is saved. A resume control handles interrupted work. Episodes share a series lookup,
ambiguous matches retain placeholders, and poster metadata updates preserve all viewing history fields.
Netflix uses a server-side TMDB Read Access Token, a source-only update RPC, and attribution under the section.
No TMDB lookup starts just by opening the page. Existing Netflix uploads need one reimport to attach lookup
keys; existing Steam snapshots need a sync/import to attach header URLs.

Catalogue-artwork checks passed at 1440px dark, 390px light and 320px dark: real public Steam/poster CDN images
rendered without overflow; post-import poster fetching started automatically; failure preserved viewing history;
resume completed multiple batches; shared posters and missing-image placeholders behaved correctly. TMDB search
responses were mocked because no TMDB token is configured. A public Steam image endpoint returned HTTP 200.
The Netflix poster RPC migration remains to be applied remotely.

Media sources are optional: empty sections show feature previews and explain that each source works
independently. Expandable Spotify/Netflix import guides and Steam/Last.fm setup steps keep server settings
out of the main flow. Sync guides distinguish the current single-account server configuration from a
connection for every member of a shared deployment. Netflix poster setup is optional and shared by the host;
missing setup leaves CSV import available and missing images use icons.

Optional-setup browser checks passed at 1440px dark, 390px dark and 320px light: all guides opened, Netflix
import succeeded with every optional key absent and made no poster request, and layouts had no horizontal
overflow. A failed Steam status endpoint preserved all sections, saved games, file import and broken-image
fallbacks. Browser fixtures intercepted API requests; no account data was changed. The preview route was removed.
# YouTube viewing journal

YouTube sits between Netflix and Steam with the same headline/logo layout, section links, reveal motion,
optional feature placeholder and import disclosure. It displays Takeout video/channel information and local
timestamps, paginates saved history and uses landscape thumbnails with play-icon fallbacks. It does not
display inferred watch-time totals. Browser checks passed at 1440px dark, 390px light and 320px dark for
section order, local logo loading, import, timestamps, links, missing thumbnails, pagination and overflow.
Tests intercepted API traffic; the temporary public preview route was removed.
