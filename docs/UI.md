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
