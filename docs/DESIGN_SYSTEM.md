# TrueUp design system

TrueUp is a workbench for payment operations and risk analysts. Every screen answers one question: what needs a
decision, and how much money is at stake. The interface makes that answer fast to find and easy to trust.

Tokens live in `dashboard/app/globals.css` (colours, type scale, radius). Components live in
`dashboard/components/ui.tsx` and `charts.tsx`. This document explains how to use them.

---

## Principles

1. **Money first.** A finding leads with its amount and its owner (merchant, issuer, payout). Signed differences
   ("−₹8,031.22") beat a bar that only says "not quite full".
2. **Proof beside the claim.** Every detector result is graded against a known answer key, and the UI says how
   ("rules in SQL, checked by tests", "graded on 200 runs").
3. **Readable without hovering.** Charts carry a labelled scale and their date range; hover adds the exact value.
4. **Two surfaces, two jobs.** Deep navy cards hold analysis (charts, the attention list, the lab). Lavender cards
   hold supporting facts and tables. Violet is the single accent: the highlighted action, selection and healthy
   state. A fintech palette: calm and trustworthy, with colour spent on state.
5. **Honest edges.** Loading, empty and failed states say what happened and what to do next.

---

## Colour

| Token | Role |
|---|---|
| `page` | White page background |
| `card` | Lavender surface: supporting cards and tables |
| `dark` / `dark-deep` | Deep navy analysis cards and primary buttons |
| `ink` | Primary text on light surfaces |
| `muted` · `on-panel-muted` | Secondary text on lavender and on white |
| `on-dark-muted` | Secondary text on navy cards |
| `line` | Hairlines and neutral chips |
| `accent` · `accent-soft` | Violet, the one accent: highlighted action, selection, healthy state |
| `alert` · `caution` | Severity dots and incident bars on navy cards (high, medium) |
| `bad` · `bad-soft` · `warn` · `warn-soft` | State on light surfaces: errors, shortfalls, warnings |
| `panel` · `panel-2` | Indigo for the processor-margin series |

Rules
- Severity colours are never decorative. Low severity uses the accent.
- Never write a hex value in a component; add a token instead.
- Contrast meets WCAG AA: secondary text is at least 6:1 on its surface.

---

## Typography

Urbanist, by role. **Never write a raw size (`text-[13px]`).**

| Class | Size / line | Use |
|---|---|---|
| `text-micro` | 11 / 14 | Axis labels, eyebrows |
| `text-caption` | 12 / 16 | Hints under figures, table headers, chips |
| `text-body-sm` | 13 / 19 | Table cells, dense lists |
| `text-body` | 14 / 21 | Default reading text |
| `text-lead` | 15 / 23 | Card titles, list item titles, intros |
| `text-heading` | 16 / 22 | Emphasised labels |
| `text-title` | 20 / 26 | Panel headlines |
| `text-section` | 28 / 34 | Section headlines on the landing page |
| `text-stat` | 40 / 40 | KPI figures (light weight) |
| `text-display` | 44 / 46 | Page titles |
| `text-hero` | 56 / 58 | Landing hero |

Rules
- Figures use `num` (tabular numerals, tight tracking).
- Currency is part of the value (`$2.5M`); a percent sits on the same baseline in a smaller size (`88.9 %`).
- One page title per page, set by `PageHeader`.

---

## Space, shape and layout

- 4px base. Cards: `p-5` (`sm:p-6`), `gap-4` between cards, `mt-5` between a page's rows.
- Page structure: `PageHeader` (title and one-line purpose), then on analysis pages (Dashboard, Approvals,
  Disputes, Fees) a row of four `Stat` figures, then filters, then cards. List pages (Exceptions, Payouts) go
  straight from the header to their filters.
- Radius: `rounded-card` (24px) for cards and the navigation; `rounded-2xl` inside cards; `rounded-full` for
  buttons, pills and chips.
- Desktop first for analysts; every page works at 390px with no horizontal page scroll. Wide tables scroll
  inside their card.

---

## Motion

- 200ms `cubic-bezier(0.22, 1, 0.36, 1)` on colour and state changes.
- Bars grow in on first paint (700ms, staggered by at most 300ms); pages enter with `rise` (360ms).
- `prefers-reduced-motion` collapses all of it.

---

## Components

| Component | Use it for | Notes |
|---|---|---|
| `PageHeader` | Every page's title and purpose | Actions sit on the right. |
| `Stat` | Headline figures | Label, value, one-line hint saying what it counts. `suffix` for %, never for $. |
| `Card` / `DarkCard` + `CardTitle` | Grouped content | Navy for analysis, lavender for supporting facts. Title is a noun phrase. |
| `Pills` | Switching one view's slice | Active pill is navy, `aria-pressed` set. |
| `Button` | Actions | `dark` primary, `accent` for the one highlighted action, `ghost` otherwise. |
| `Chip` / `statusTone` | Short state labels | Tone follows state: open is `bad`, resolved `accent`, explained `dark`. |
| `Bars` | Daily series | Labelled scale with a rounded baseline (`niceFloor`) so dips are visible but not exaggerated; date range under the bars; optional selection and highlighted incident days. |
| `Lines` | A few series on one x axis | Legend shows each series' last value. |
| `Meter` | Share of a whole in a table row | Not for values that are almost always 100%. |
| `Skeleton` / `CardSkeleton` | Loading | Shaped like the content that is coming. |
| `EmptyState` / `ErrorState` | Nothing to show, or a failure | Errors explain the free API's cold start and offer a retry. |

---

## Accessibility

- Skip link, landmarks, one `h1` per page; tables have captions and scoped headers.
- Every interactive element has a visible violet focus ring; bars are focusable and named with their value.
- Status is never colour alone: severity dots carry a label, chips carry text.
