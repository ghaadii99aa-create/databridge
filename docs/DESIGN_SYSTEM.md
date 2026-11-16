# Design system

DataBridge is a tool people work in for hours, reading tables and comparing numbers. The design follows from
that: quiet surfaces, strong type hierarchy, numbers that line up, and colour used only where it carries
meaning. Tokens live in `frontend/tailwind.config.js`; shared components in `frontend/src/components`.

## Colour

| Token | Hex | Role |
|---|---|---|
| `paper` | `#F7F6F2` | Application background (warm off-white) |
| `surface` | `#FFFFFF` | Tables and panels, the places where data sits |
| `ink` | `#242824` | Text, table header rules, the ETL stage track, active tabs |
| `ink-muted` / `ink-faint` | `#5E625B` / `#686C65` | Secondary text / zeros, row numbers, placeholders |
| `forest` | `#526B58` | The working colour: primary actions, selected state, good quality, single-series charts |
| `sage` | `#DCE5DC` | Success badges, applied filters, selection highlight |
| `stone` | `#E8E6DF` | Sidebar, skeletons, neutral badges, dividers |
| `clay` (`clay-deep`) | `#B87559` (`#8A5039`) | **Attention only**: quality issues, failures, poor scores, destructive actions. Text uses `clay-deep` for contrast |
| `amber` | `#A9851C` | Warnings and the "Sample data" label |

Rules:
* Terracotta (`clay`) never decorates. If it is on screen, something needs a look.
* Status always comes with text and an icon (`Succeeded ✓`, `Failed ✕`), never colour alone.
* No gradients, glows, glass effects or neon. Shadows exist only on floating layers (dialogs, toasts, tooltips).

### Chart palette

Charts use a fixed categorical order derived from the brand hues with more chroma, so series stay
distinguishable. It was checked with a colour-vision-deficiency validator (lightness band, chroma floor,
adjacent-pair ΔE under protan/deutan/tritan simulation, normal-vision floor, contrast against white). All
checks passed; the worst adjacent pair has ΔE 9.9 under deuteranopia.

`#2F7F47` `#8C4F86` `#B8623C` `#3366AE` `#A9851C` `#00897B`

The order is fixed and never cycled. The comparison chart shows at most six split values, so it never runs
out of colours. Single-series charts use brand `forest`. Every chart has a **Table** view with the same
numbers.

## Typography

**IBM Plex Sans** (400/500/600), self-hosted through `@fontsource` (latin subset only), so no third-party font
CDN and no layout shift from late font swaps. It was designed for technical interfaces and has clear figures.
Tables and figures use `font-variant-numeric: tabular-nums` so digits align in columns.

| Step | Size / line height | Use |
|---|---|---|
| `2xl` | 36/40, −0.02em | Hero numbers (quality score) |
| `xl` | 26/32, −0.01em | Page titles, figures |
| `lg` | 20/28 | — |
| `md` | 16/24 | Section titles |
| `base` | 14/22.4 | Body and controls (dense tool default) |
| `sm` | 13/20 | Tables, secondary text |
| `xs` / `2xs` | 12 / 11 | Captions, units, tags |

Sentence case everywhere; no all-caps labels.

## Shape and space

* Radius: 4 px for controls and 6 px for panels. The stage track and tables keep square inner edges.
* Borders: 1 px `#DEDBD2` hairlines. Table headers sit on a dark 1 px rule (`ink`), which anchors the column
  names without boxing every cell.
* Spacing on a 4 px grid; sections are separated by 36 px. Content is capped at 1240 px wide.

## Signature elements

1. **Weighted quality bar.** One bar split into four segments whose widths are the scoring weights
   (30/30/20/20). Each segment fills to its dimension's score, so the filled area of the whole bar is the score.
   The number and the method are shown together.
2. **ETL stage track.** A real sequence, so its stages are numbered. Completed stages turn charcoal and show
   their duration, the running stage is sage, and a failed stage is terracotta.
3. **Execution log.** A dark log table with millisecond timestamps, so a run reads like an operations console.

## States

| State | Treatment |
|---|---|
| Empty | Dashed outline, a plain statement, and the action that fills it ("Load sample dataset") |
| Loading | Skeleton bars with the shape of the content; `aria-busy` |
| Error | Terracotta-tinted panel with the server's message, the request ID, and "Try again" |
| Success | Short toast naming what happened, using the same verb as the button ("Pipeline created") |
| Not applicable | Charts that cannot be drawn say why ("No date column was detected…") instead of drawing |

## Motion

One 160 ms fade on route change, spinners for work in progress, and a progress bar for uploads. Chart
animation is disabled. `prefers-reduced-motion` turns transitions off.

## Accessibility

Skip link, visible focus ring (2 px forest), native `<dialog>` for confirmations (focus trap and Esc), labelled
form controls, `aria-sort` on sortable headers, `aria-live` regions for toasts and analyst answers, and table
views for every chart.

Text contrast was computed with the WCAG 2.x formula for the pairs used in the interface, and the tokens were
darkened where a pair failed AA (4.5:1). Current values: body text 13.8:1, secondary text (`ink-muted`) 5.3:1 on
the sidebar, faint text (`ink-faint`) 4.6:1 on the sidebar and 5.4:1 on white, the failure badge 5.2:1, and
white on the high-severity tag 6.4:1. No automated audit tool (such as axe) has been run yet; that is on the
roadmap.
