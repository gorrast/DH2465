# StressLess design specification

## Scope and rationale

StressLess relates calendar context, watch measurements and sleep history, then proposes changes to an evening plan. Show the observation, its uncertainty and one practical action. Label simulated data explicitly. Do not imply diagnosis or causality.

The direction, **After Hours**, combines editorial typography, dark navy surfaces, restrained light and progressive disclosure. All pages share its surfaces and typography. Today implements the full editorial composition; other views retain their existing layouts and semantic colours. This document specifies the target, not a claim of complete implementation.

Documentation must use concise, factual, research article-like language. Distinguish observations, requirements and verified results. Remove repetition, promotional claims and chronological work logs.

## Reference principles

These observations describe the regional pages inspected on 21 October 2026; campaigns can change. The typography and tokens below are original StressLess choices.

| Reference | Grid and whitespace | Typography and colour | Omission and adopted principle |
|---|---|---|---|
| [Oura](https://ouraring.com/) | Broad photographic stages; separate headline, explanation and action | Light editorial sans-serif; warm cream, stone and linen tones | Opening omits dense metrics. Adopt warmth and reading rhythm. |
| [Ultrahuman](https://www.ultrahuman.com/se/) | Inset product stage; left copy/right object; isolated evidence panels | Geist sans-serif; neutral surroundings, metallic imagery, concentrated blue action | Opening omits specification tables. Adopt isolated demonstrations and material lighting. |
| [WHOOP](https://www.whoop.com/se/en/) | Full-width image/video stage; large left headline; wide subsequent sections | Proxima Nova with sans-serif fallbacks; black/white with campaign violet/blue | Opening omits dashboard density. Adopt a clear focal point and product-to-action sequence. |

Use an actual score, selected timeline or protected evening block as the product close-up. Do not borrow hardware, proprietary assets, athletic urgency or brand identity.

## Composition and layout

Entry sequence: evening summary → calendar/physiology example → supported Planner adjustment → evidence limits → data scope and account action. Keep the same simulated day throughout. Use “Create a demo account” until anonymous exploration exists. Never bypass authentication for a visual demonstration.

Today opens with a large night date above a two-column headline and sleep score (up to 520px ring). Stack the headline and score on phones. Put rating, baseline, sleep duration and wake time in a separate section before the suggested action; use large values and readable labels. Keep the number steady; breathe the sunrise-red/peach halo and ring opacity in phase over ten seconds. Finding titles use 22–28px desktop/20px phone text; signed associations use pastel green/up arrows for positive values and pastel red/down arrows for negative values, with darker accessible equivalents in light mode. Zero, unavailable values and changes rounding to zero remain neutral without directional arrows. Use the shared score renderer across views, tables, chart labels and tooltips; colour interval endpoints independently. Deduplicate repeated finding/evidence text without removing charts. Display duration comparisons once, at 19px, and highlight the higher duration green and the lower duration red; equal or missing comparisons remain neutral. Provide pause and reduced-motion fallbacks. The editorial headline and ring are the two focal elements. Move sleep summary, tonight’s action, findings, day trace and recovery markers into separate scroll-entry sections with 80–144px vertical padding (72px on phones). Keep chart detail expandable and numbers prominent. Sentence case is the default.

| Token/rule | Desktop ≥1200 | Tablet 768–1199 | Phone <768 |
|---|---|---|---|
| Content grid | 12 columns | 8 columns | 4 columns |
| Column gap | 24 | 24 | 16 |
| Outer gutter | 48 | 32 | 20; 16 below 360px |
| Entry content max-width | 1280, centered | available width | available width |
| Application content max-width | 1280 within shell | available width | available width |
| Main narrative section spacing | 128 | 96 | 64 |
| Application section spacing | 48 | 40 | 32 |
| Entry hero padding, top/bottom | 96/96 | 72/72 | 48/48 |
| Application header height | 72 | 64 | 64 |
| Navigation | 48px reveal edge; 216px overlay drawer | Same drawer with explicit toggle | Bottom bar plus safe-area inset |
| Card padding | 32 | 24 | 24; 20 below 360px |

Use `minmax(0, 1fr)` columns and `min-width: 0` children. Text measures: headline ≤24ch, explanation ≤56ch, evidence ≤68ch. Each section contains one claim, supporting visual and at most one primary action. Use open sections with separators; reserve cards for independent actions or comparable items.

Use one shared 216px overlay sidebar with a page-coloured surface, regular 13px links and the coral StressLess mark. Show a bordered Menu trigger with a visible “Hover or click” hint. Open on edge hover or the labelled toggle. Closed content is inert. Escape closes and restores toggle focus. Preserve bottom navigation on phones. Explore the demo uses a persistent down/up chevron and indented destinations. Keep Today, Replay, Insights and Plan primary. Put experimental views under More/Explore. Keep privacy within two actions. Fixed navigation must leave focused content visible. Dense charts may scroll locally with an affordance and readable alternative; page overflow is a defect.

## Tokens

Use semantic custom properties. Shared navy/cream surfaces and font assets are defined in `styles/base.css`. Today retains scoped text and action colours. Preserve other views' existing accent, status and chart palettes. Shared definitions belong in `styles/base.css`; Today-specific presentation belongs in `styles/views/morning.css`. Consolidate existing rules rather than appending overrides. Preserve stylesheet import order.

| Semantic token | Default dark | Explicit light theme | Meaning |
|---|---|---|---|
| `--page` | `#141C32` | `#F5EDDF` | Main canvas |
| `--card` | `#1B2640` | `#FFFAF1` | Independent surface |
| `--card-2` | `#23304A` | `#EEE4D5` | Hover/selected neutral surface |
| `--card-3` | `#283449` | `#E3D7C5` | Pressed surface/chart track |
| `--ink-primary` | `#F2F0E9` | `#202724` | Essential text |
| `--ink-secondary` | `#B8BFBA` | `#4D5C54` | Supporting text |
| `--ink-muted` | `#929E97` | `#5D6B63` | Secondary metadata; never reduce with opacity |
| `--hairline` | `#34415C` | `#D0D4CA` | Decorative separator, not a control boundary |
| `--control-border` | `#78877F` | `#6A7A70` | Essential field/control boundary |
| `--interactive` | `#C9B5ED` | `#68458F` | Clickable text and primary action fill |
| `--interactive-hover` | `#E0CFF9` | `#513371` | Hover and selected controls |
| `--interactive-ink` | `#251B35` | `#FFFFFF` | Text on primary fill |
| `--score-positive` | `#A4D6B3` | `#34704A` | Positive sleep-score changes; higher compared duration |
| `--score-negative` | `#EFA5A0` | `#A34743` | Negative sleep-score changes; lower compared duration |
| `--focus` | `#E2EFDE` | `#235B45` | Keyboard focus, never ornamental glow |
| `--sleep` | `#B7A9DD` | `#68588E` | Sleep-stage/summary emphasis |
| `--recovery` | `#8ABCAF` | `#336B5C` | Recovery markers, not an invented readiness score |
| `--activity` | `#D8B77B` | `#815F24` | Activity/context highlight |
| `--danger` | `#EBA49E` | `#A13E39` | Failure/destructive action |
| `--warning` | `#DDC185` | `#795A17` | Incomplete evidence requiring attention |
| `--success` | `#A8CCB5` | `#316548` | Confirmed completion |

Use one accent per narrative section. Chart categories retain stable colours and legends across views. Missing data uses explicit text and dashed/hatch marks. Check contrast on actual blended surfaces: 4.5:1 normal text; 3:1 large text and essential boundaries. Colour alone must not encode meaning.

Theme precedence: explicit URL → saved preference → dark. Use the independent `--interactive` family for controls; preserve `--accent` and chart/status colours for existing semantic content. Primary controls use a purple fill and contrasting text; secondary controls use purple text. Disclosures show an open/closed indicator. Disabled controls use muted text and no hover/press feedback. Selected and danger washes use their semantic RGB at 10% opacity; keep text solid.

Use bounded radial washes: sleep 12%, recovery 10%, evening 8%; transparent by 68%. Maximum two washes per viewport. Place the brightest area behind the visual. Ordinary cards have no shadow; overlays may use `0 20px 64px rgb(0 0 0 / .28)` with a 1px edge. Never animate blur.

Self-host Manrope for body, controls and numbers; Newsreader for editorial headings. Use Arial/Georgia fallbacks, WOFF2 and `font-display: swap`. Retain font licences.

| Role | Desktop / phone size | Line-height | Weight | Tracking |
|---|---|---|---|---|
| Entry display | 80 / 44 | 1.08 | Newsreader 400 | -0.025em |
| Editorial section | 56 / 36 | 1.12 | Newsreader 400 | -0.02em |
| Application page title | 40 / 30 | 1.2 | Manrope 400 | -0.025em |
| Section title | 28 / 24 | 1.25 | Manrope 500 | -0.015em |
| Score numeral | 164 / 100 | 1 | Manrope 400 | -0.04em |
| Lead copy | 20 / 18 | 1.6 | Manrope 400 | 0 |
| Body/field | 16 / 16 | 1.6 | Manrope 400 | 0 |
| Control label | 14 / 14 | 1.2 | Manrope 500 | 0 |
| Metadata | 13 / 13 | 1.5 | Manrope 400 | 0 |
| Chart axis/eyebrow | 12 / 12 | 1.4 | Manrope 500 | 0; eyebrow only +0.08em |

Use tabular numerals for changing values. Keep units adjacent and one size smaller. Serif type is excluded from forms, chart axes and navigation. Use `clamp()` for responsive headings.

| Scale | Allowed values |
|---|---|
| Spacing | 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 96, 128 |
| Radius | 4px marks; 8px small controls; 16px fields; 24px cards; 32px image stages; 999px pill actions |
| Border | 1px ordinary edge; 2px selected/invalid edge; 3px focus outline |
| Focus offset | 4px, with a dark/light surface moat if imagery makes contrast uncertain |
| Icon | 16px inline metadata; 20px controls; 24px primary navigation; 1.75px stroke |
| Control hit target | Minimum 44×44px, including icon controls and segmented options |
| Z-index | 0 canvas; 1 wash/decoration; 10 content annotation; 20 sticky header; 30 popover; 40 bottom nav; 50 toast; native dialog top layer |

## Components

| Pattern | Required behaviour |
|---|---|
| Score summary | One sleep ring, actual value, personal baseline and missing-data state; no invented readiness score |
| Finding | Plain-language association, magnitude/range and sample size; expandable evidence linked to the timeline |
| Timeline | Stable event categories, selected time/window and labelled inspector; keyboard/touch equivalent to pointer details |
| Recovery markers | Comparable values with units and baseline; additional metrics disclosed on request |
| Suggested change | Supported Planner operation, estimate range, guarded save, persistent failure/retry and optional `.ics` export |
| Field | Persistent label, help/error association, native semantics; never placeholder-only |
| Disclosure | Native details or button with `aria-expanded`, stable `aria-controls` and named content |
| Dialog | Native dialog, safe initial focus, containment, Escape and focus return |
| Status | Name the operation; persistent inline error; toast may supplement but never replace it |

Use existing React, CSS and SVG. Add dependencies only for a concrete requirement that this architecture cannot maintain simply. Keep static chart layers memoized. Use at most one contextual lifestyle image on entry; reports use actual data. Avoid autoplay video and decorative 3D. Supply dimensions, responsive sources, useful alternative text and lazy loading below the fold.

## Motion

`ease-ui = cubic-bezier(.2,0,0,1)`; `ease-out = cubic-bezier(.22,.61,.36,1)`. Focus outlines appear immediately.

| Interaction | Duration | Easing | Animated properties | What it communicates |
|---|---|---|---|---|
| Primary button hover | 260ms | ease-out | `background-color`, `border-color`, `transform: scale(1.035)` | This action is available. |
| Primary button press/release | 260ms | ease-out | `transform: scale(0.965)` → 1 | The press registered. Hover remains suppressed when disabled/loading. |
| Field focus | 160ms | ease-ui | `border-color`, a subtle surface `background-color` | The typing location is clear. The required focus outline appears immediately at 0ms. |
| Interactive card hover | 200ms | ease-ui | `background-color`, `border-color`, optional `translateY(-2px)` | This whole card opens/selects something. A static information panel never lifts. |
| Page section entry | 1000ms | ease-out | `opacity: 0 → 1`, `translateY(28px → 0)` | A new idea has entered the reading sequence. Run once per section per visit. |

Login and Today headlines: 1200ms per line with a 250ms offset and 24px movement, once; no font-load gate. Hero background only: scroll-linked scale 1–1.28 and opacity 1–0.15 over the hero exit plus 35% viewport travel; keep text and score stable. Primary actions: hover scale 1.035, press scale .965, 260ms; suppress while disabled, busy or reduced motion. Sidebar links: 110ms stagger, 450ms/16px item entry; focus reveals immediately. Recovery markers: 110ms stagger, 650ms/16px item entry. New planner cards and save confirmations: 600ms opacity/12–16px entry; existing cards retain identity.

Evidence expansion: 480ms ease-out, height and opacity; collapsed content remains inert. Initial score arc: 700ms ease-out, once; show the final number immediately. Timeline selection: 180ms ease-ui on fill/stroke; direct seeking is immediate. Save confirmation: 600ms ease-out with stable occupied space. Overlay entry/exit: 160/120ms opacity.

Use Motion viewport observation for once-only section entry at 92% viewport height. Initial HTML remains visible; only below-fold sections wait for entry. Reveal immediately on focus, pause or reduced motion. With reduced motion, remove transforms, arc drawing, smooth scrolling and automatic media. Explicit Replay play/seek remains available. Stop playback on exit. Only the score’s optional ten-second breathing loop may repeat; retain pause and reduced-motion controls. Today uses native vertical proximity snapping on stable section boundaries, with 88px top clearance (84px on phones) and normal snap-stop behaviour. Tall sections and expanded details remain freely scrollable. Disable snapping and smooth scrolling for reduced motion or Pause motion. Other pages keep normal scrolling. No count-up, scroll interception or `transition: all`.

## Interaction state contract

Apply every column below to each interactive instance. “N/A” requires a behavioural reason: local controls need no network loading state; links expose errors at their destination. Disabled and loading states suppress hover/press effects. Focus remains visible on every focusable state.

| Element | Default | Hover | Focus-visible | Active | Disabled | Loading | Error |
|---|---|---|---|---|---|---|---|
| Async button | Named operation | Action-hover fill | Immediate 3px outline, 4px offset | 0.98 scale | Muted surface, reason | Preserve focus; pending verb, busy status, duplicate guard | Persistent inline message and retry |
| Link/navigation | Named destination | Underline or neutral fill | Same outline | Press feedback; persistent current marker separately | Remove unavailable destination or explain | Pending destination region | Destination retry/context |
| Choice/tab | Named choices | Neutral fill | Same outline; complete keyboard pattern | Persistent selected marker and semantics | Unavailable reason | Only for dependent fetch | Retain selection; dependent-region failure |
| Field/select/upload | Label, boundary, help | Stronger boundary | Immediate outline; focus border | Native editing/selection | Native disabled and reason | Associated status for validation/import | Invalid semantics plus attached message |
| Disclosure/menu | Named trigger | Text/surface emphasis | Same outline | Expanded indicator and semantics | Only when unavailable | Only for lazy content | Attached content failure |
| Range/scrubber | Label and formatted value | Track/thumb emphasis | Same outline; arrow/Home/End support | Inspector follows immediately | Explain absent data | Only for dependent fetch | Region failure and retry |
| Interactive card/chart | Named selection and readable data | Boundary/inspector emphasis | Same outline; equivalent details | Persistent selection marker | Explicit unavailable data | Associated region status | Attached failure; missing value never zero |
| Dialog/media controls | Named operation | Button treatment | Initial/return focus; containment when modal | Control-specific state | Boundary reason | Only for remote work | Retained context and recovery |

State precedence: error describes the affected field/region; pending blocks duplicate actions; disabled blocks activation; focus is additive; persistent selection survives transient hover/press. Static information cards have no interaction states.

## Implementation status and outstanding audit

The earlier audit preceded the Today redesign. Its Today findings must not be treated as current defects. Today now has guarded save/export, inline errors, evidence relationships, keyboard time inspection and readable evidence/stage tables. This cleanup does not re-audit every interaction.

| Area | Outstanding verification or previously identified gap |
|---|---|
| Shared navigation | Route pending/error presentation; nested selection; mobile focus visibility |
| Persona and sign-out | Per-action pending/error; persona selection semantics; busy overlay background focus |
| Replay | Speed selection semantics; next-event boundary; pointer/keyboard detail parity; reduced-motion playback |
| Insights, Habits, Reality, Media, Lab | Keyboard/touch alternatives for chart detail; field-linked import/errors; fetch status |
| Authentication | Complete tab semantics or ordinary choice buttons; field error associations and pending labels |
| Tour | Initial/return focus, key interception, named previous control and reduced-motion scrolling |
| Shared controls | Disabled hover/press suppression, segmented choice states and error-region semantics |

The source audit found a global focus-visible rule and no first-party `outline: none` reset. Pointer-only controls, lost focus and clipped outlines remain accessibility bugs even when a global rule exists. Never remove focus indication. Recheck findings against current code before marking them resolved.

## Generic element review

Each element must explain this product's data or action. The following decisions are prescriptive; they do not imply these elements are installed.

| Generic element | Decision for StressLess |
|---|---|
| “Unlock your potential,” “Your day has a story,” “Understand yours” | Replace with “See what your day leaves behind” plus “Compare your calendar with your body's response and last night's sleep.” |
| A pill announcing “AI-powered” | Omit. Lead with the actual calendar/body explanation. Identify optional narrative generation in report details. |
| Oversized gradient-coloured hero word | Replace with a real sleep value and baseline, using a stable semantic colour. Headline remains solid readable type. |
| Generic purple/blue aurora background | Replace with the bounded sleep/evening wash specified under Tokens, attached to the current scene's meaning. |
| Floating glass cards and blurred neon blobs | Replace with a solid score surface and one sharp calendar/physiology trace. Every number must be legible. |
| Hero dashboard screenshot unrelated to its copy | Replace with the same synthetic evening used in Replay and Planner. Selection must connect the claim to visible evidence. |
| 3D ring/watch/phone rotating endlessly | Omit invented hardware. Use a close-up of our protected time block or score arc. A phone frame earns no space unless it explains an actual mobile interaction. |
| Generic animated particles, orbs, beams, sparkles | Omit. The moving cursor, selected response window, and opening evening gap already supply meaningful motion. |
| Six equal feature cards with stock icons | Replace with three sequential product beats: observe the day, inspect the evidence, try one evening change. |
| A bento grid because it looks modern | Use a grid only for comparable recovery markers or data connections. Keep the central explanation sequential. |
| “Everything you need in one place” | Replace with the exact inputs and limit: calendar context, watch measurements, location confirmation; gaps stay visible. |
| Three-step “Connect / Analyze / Optimize” | Replace with a single witnessed example: late call → elevated evening trace → associated sleep pattern → proposed earlier finish. |
| Arbitrary “10× better,” “99% accurate” counters | Omit. Show the engine's actual sample size, typical error and out-of-sample fit in technical evidence, clearly labeled. |
| Continuously counting community statistics | Omit. No invented live user, sleep-night, success or accuracy totals. A user's own history count is useful without a count-up. |
| “Trusted by” brand-logo strip | Omit until real relationships exist. A Calendar/Watch/Maps source row is a data-input explanation, not an endorsement. |
| Fake testimonials and stock avatar stack | Omit. Demo personas are labeled simulated people, never customers or social proof. |
| Five-star ratings and review ticker | Omit without attributable genuine reviews. Do not use app-store-style credibility decoration. |
| Unverified science/certification badges | Replace with a link to the model's actual validation and explicit simulated ground truth. No borrowed medical authority. |
| Integration logo wall | Replace with connection rows showing implemented import, simulated source, planned integration, fields and retention. |
| Competitor comparison/checkmark table | Replace with a trace showing what a score alone misses and what StressLess can actually explain. Avoid unsupported claims about competitor products. |
| Pricing cards, “Most popular,” monthly/yearly toggle | Omit until a real commercial offer and billing implementation exist. Demo account creation does not need a pricing scaffold. |
| Hero “Start free trial” with no trial | Use “Create a demo account.” Do not imply paid billing, a trial period or anonymous access that does not exist. |
| Newsletter/waitlist email capture | Omit unless collecting those subscriptions is a real project goal with a working flow. Login email is for authentication, not marketing. |
| Repeated identical CTA after every section | Use one primary action at the start and end of the entry sequence; contextual actions in between must do something different and useful. |
| Generic question accordion (“Is it easy?”) | Replace with specific answers: simulated vs imported data, missing nights, association limits, retention, and what saving/exporting a plan does. |
| Decorative FAQ chevrons or fake plus buttons | Omit unless a real disclosure exists with keyboard, open/closed and focus states. |
| Generic wave/curve divider between every section | Use spacing and a fine separator. A sleep-stage band belongs only where it encodes actual stages. |
| Endless marquee/carousel | Omit. A selected day or pattern has a clear starting point and user-controlled navigation. Do not auto-rotate content. |
| Typewriter headline and letter-by-letter reveal | Omit. Login and Today headings may reveal complete lines once (1200ms per line, 250ms stagger); retain readable initial HTML and an intact accessible heading. |
| Scroll-jacked “immersive” product story | Omit. Use normal document flow and optional one-stage sticky illustration with a static fallback. |
| Hover tilt/magnetic button/custom cursor | Omit. They add tracking and motion without explaining a stress/sleep decision. |
| Confetti, streaks, trophies and “crushed it” praise | Replace with calm confirmation: “Saved to your plan.” Protecting rest must not become another performance obligation. |
| Floating AI chatbot bubble | Omit. The product's explanation and evidence are the relevant guidance; do not create a second ungrounded advice surface. |
| Generic code terminal/API snippets | Keep technical implementation only in Under the hood when useful to this course demo. Never put it in the wellbeing journey as decoration. |
| A large multi-column corporate footer | Keep only working links: privacy/data scope, methodology, project information, sign in and available contact. No empty “Careers,” “Enterprise,” or “Press” destinations. |
| Stock smiling professionals, athletes, or sleeping models as proof | Use at most one contextual entry photo with honest captioning; put actual product data in reports. Never imply the pictured person supplied the data. |
| “Secure,” lock, GDPR or compliance badges without substantiation | Replace with concrete storage, access and deletion behavior supported by the code. Branding cannot establish compliance. |
| Tiny gray uncertainty disclaimer below the fold | Promote sample size and range to the finding/forecast they qualify. Keep them readable, including on mobile. |
| Technical chips everywhere | Retain only date, source status, confidence/sample, or selection metadata needed for the current decision. Convert prose into sentences rather than chip confetti. |
| Card lift on every panel | Only interactive navigation/selection cards lift. Static findings, chart frames and narrative sections stay still. |
| A “live” badge on deterministic simulation | Replace with “Simulated example” or a timestamped real source label. Replay playback is not real-time sensing. |

## Copy and prohibited patterns

Use sentence case, short verbs and one claim per sentence. Prefer “sleep”, “your usual”, “recovery” and “room to rest”. Headline ≤10 words; action label preferably 2–4 words. Evidence and error messages may exceed these limits when required for accuracy.

| Situation | Use | Never use |
|---|---|---|
| Association | “Later meetings were followed by lower sleep scores in your recent history.” | “This meeting caused your poor sleep.” |
| Forecast | “Estimated change: +1 to +8 points.” | “Get 8 more points tonight.” |
| Confidence | “Based on 12 similar nights. Evidence is still limited.” | “Your body definitely needs…” |
| Missing data | “Watch data is unavailable for this night.” | “You failed to wear your watch,” or a zero score |
| Cold start | “Building your baseline: 7 of 10 nights.” | “Nothing to see here.” |
| Save | “Saved to your StressLess plan.” | “Synced to Google Calendar” unless that write actually happened |
| Export | “Download calendar file (.ics).” | “Connected” when only a file was downloaded |
| Async action | “Saving…”, “Importing…”, “Preparing your report…” | A spinner with no named operation |
| Error | “We couldn't save that answer. Your question is unchanged. Try again.” | “Oops! Something went wrong” as the only explanation |
| Demo | “Simulated example · Alex · 65 recorded nights.” | “Live health analysis” |
| Confirmation | “Delete answers and saved plan blocks?” plus the exact actual scope | “Delete everything” if some classes remain |

Never invent clinical claims, scores, customers, certifications, progress or remote-write success. Do not infer diagnosis from anomalies. Do not use guilt, urgency, streak loss, confetti or athletic praise. Never hide uncertainty or simulated status. Never require hover, animation, a font load or a repeated reveal gate to access essential content. Avoid card grids, badges and decorative rings where ordinary text is clearer.

## Acceptance

Run `npm run typecheck` and `npm run build`. Use the existing browser workflow; do not add a second test stack. Verify both themes at desktop, tablet, 390px and 320px widths; include 200% zoom, touch, keyboard and reduced motion. Check page overflow, focus clipping/return, score-focused first-viewport hierarchy and contrast.

Exercise slow, failed, empty, missing-watch and insufficient-history responses. Reject stale results and duplicate writes. Confirm save/export wording matches actual behaviour. Record verified outcomes separately from requirements in `docs/UI.md`.
