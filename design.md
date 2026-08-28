# design.md — UI design spec (POC)

For the frontend build. Codex/any UI dev: follow these tokens exactly; don't invent colors or fonts. Product context in `PRD.md`, layout logic in `architecture.md`. Reference: the "Evidence Rail" screenshot.

---

## 1. Design thesis — "instrument, not app"

A prescription is a legal medical document signed by a doctor. The screen should feel like a **precise clinical instrument**: quiet, dense but legible, fast to scan, calm under pressure.

**One governing rule: color = clinical signal.** Color appears only to carry safety meaning (pass / warn / severe / not-checked) and the single primary action. Everything else is ink on paper. Because nothing else is colored, a warning is physically impossible to overlook.

**One functional type decision:** every clinically-actionable number — dose, strength, frequency count, daily total, encounter ID, timestamp — is set in **monospace, tabular figures**. A doctor must never misread `1300 mg`. Legible numbers are a safety feature here.

---

## 2. Color tokens

Cool clinical paper, deep slate ink, one trustworthy teal for action, four reserved safety semantics.

```
  Base
  --paper        #F7F9FA   app background (cool clinical white, not pure white)
  --surface      #FFFFFF   cards, inputs, panels
  --ink          #111827   primary text
  --ink-muted    #5B6B7B   secondary text, labels, meta
  --hairline     #E3E8EC   borders, dividers (1px)
  --hairline-soft #EEF2F4  inner rules, table lines

  Action (teal — ONLY for primary action + brand)
  --accent       #0F766E   Approve & Sign, brand mark, primary links
  --accent-weak  #E6F1EF   accent wash (AI-filled field highlight, active nav)

  Safety semantics (RESERVED — never used decoratively)
  --safe         #0E7A4B   check passed        (green)
  --safe-weak    #E7F3EC
  --warn         #B45309   caution, review     (amber-brown, readable)
  --warn-weak    #FBF0E4
  --severe       #B42318   dangerous           (clinical red)
  --severe-weak  #FBEAE8
  --unknown      #6B7280   not checked / uncovered (deliberately grey — no false green)
  --unknown-weak #F1F3F5
```

Rule of thumb: **teal = "do this", green/amber/red/grey = "this is the safety state", ink/paper = everything else.** No other color enters the UI.

---

## 3. Typography

Two families from one engineered superfamily: **IBM Plex Sans** (UI) + **IBM Plex Mono** (all clinical data). Both free (Google Fonts). Plex reads as precise and instrument-like, not the default Inter.

```
  Role            Family            Size / weight / spacing            Used for
  ─────────────────────────────────────────────────────────────────────────────
  Patient name    Plex Sans         20px / 600                         header identity
  Eyebrow         Plex Sans         12px / 600 / +0.08em / UPPERCASE / muted   "DIAGNOSIS", "PRESCRIPTION"
  Body / label    Plex Sans         13px / 500                         field labels, nav
  Input text      Plex Sans         14px / 400                         text the doctor types
  Clinical data   Plex MONO         14px / 500 / tabular-nums          dose, strength, freq, duration, IDs, times
  Safety label    Plex Sans         13px / 600                         "Dose check", "Allergy check"
  Caption / meta  Plex Sans         12px / 400 / muted                 timestamps, sub-lines, coverage text
```

**Monospace applies to:** `650 mg`, `1 tablet`, `every 6–8 h`, `3 days`, `1300 mg/day`, `ENC-20260731-0012`, `10:02 AM`, registration numbers. Not to prose instructions ("Take after food").

---

## 4. Spacing, radius, elevation

```
  Spacing scale   4 · 8 · 12 · 16 · 24 · 32 · 48   (px)
  Radius          card 8 · input 6 · pill 999 · button 6
  Border          1px --hairline everywhere; the UI is FLAT
  Elevation       none by default (hairlines do the work)
                  ONE soft shadow, reserved: sticky sign-bar + modals
                  shadow: 0 1px 3px rgba(17,24,39,.06), 0 4px 16px rgba(17,24,39,.06)
```

Clinical = flat and precise, not glossy. If you reach for a shadow anywhere but the sign-bar or a modal, stop.

---

## 5. Layout — three-column clinical console

```
  ┌───────────────┬──────────────────────────────────────────┬────────────────────┐
  │ LEFT RAIL     │  CENTER — the working document           │  SAFETY RAIL (right)│
  │ (evidence /   │                                          │  ← the signature    │
  │  mode / nav)  │  Patient header: name · age · sex · wt · │                     │
  │               │  allergies · encounter ID · date · mode  │  Safety status      │
  │  Mode 3:      │  ──────────────────────────────────────  │   ● Interaction     │
  │  transcript   │  DIAGNOSIS  [editable]                   │   ● Allergy         │
  │  streams      │  ──────────────────────────────────────  │   ● Dose            │
  │  live,        │  PRESCRIPTION (AI-staged draft)          │   ● Age             │
  │  Doctor /     │   ┌────────────────────────────────────┐ │  ──────────────     │
  │  Patient      │   │ Rx item card: generic · brand ·    │ │  Warnings (n)       │
  │  labels       │   │ strength · form · route            │ │  Evidence coverage  │
  │               │   │ dose · freq · duration · instrs    │ │   ▓▓▓▓▓░ n of n      │
  │  Modes 1/2:   │   │ [Evidence: transcript 10:07 ↗]     │ │  Clinical reminders │
  │  collapses,   │   └────────────────────────────────────┘ │                     │
  │  mode switch  │   + Add medicine                         │                     │
  │  lives here   │  Notes (optional)                        │                     │
  │               │                                          │                     │
  ├───────────────┴──────────────────────────────────────────┴────────────────────┤
  │  STICKY SIGN BAR:  "AI-staged draft · Review required. You are in control."     │
  │                                    [ Save draft ]   [ Approve & Sign ]          │
  └─────────────────────────────────────────────────────────────────────────────────┘
```

- Left rail width ~320px, right rail ~300px, center fluid.
- Left rail **content depends on mode**: Mode 3 = live transcript evidence; Modes 1/2 = compact, mode switch + patient list.
- Below ~1100px: safety rail collapses to a sticky summary chip that expands; below ~760px: single column, safety rail becomes a top banner. Never hide safety state on mobile.

---

## 6. Component inventory + states

### 6.1 Rx item card
Fields: generic (ingredient)*, brand (from catalog dropdown), strength*, form*, route, dose*, frequency*, duration*, patient instructions. Plus evidence link + per-item safety flag.

States:
```
  ai-filled    field carries a --accent-weak wash for ~1s after auto-fill, then fades
               → signals "AI put this here, review it" (distinct from doctor-typed)
  edited       doctor changed an AI value → small "edited" meta tag
  linked       evidence present → "Evidence: Doctor 10:07 ↗ View in transcript"
  missing_ctx  no evidence → inline --warn banner "Missing context … Resolve"
  uncovered    ingredient not in formulary → --unknown note "Not in safety DB — verify manually"
```

### 6.2 Safety rail rows (Interaction · Allergy · Dose · Age)
Each row = icon + label + sub-line + state color. **Never color-only** — always icon + text label too (colorblind-safe, clinical requirement).
```
  pass       --safe check ·  "No interaction risk" · "Checked 10:12 AM"
  warning    --warn  ·  "1 unresolved" · expands to detail + [Acknowledge]
  severe     --severe ·  "Dose above safe range" · expands to detail + [Acknowledge]
  uncovered  --unknown ·  "Not checked — verify manually"
  pending    neutral spinner · "Checking…"  (while safety engine runs)
  acknowledged  collapses to muted line: "Acknowledged by Dr Rao · 10:14 · reason"
```

### 6.3 Warning banner (inline, center column)
`--warn-weak` background, `--warn` left border, plain-language message, right-aligned **Resolve** / **Acknowledge**. Copy names the problem and the fix — see §8.

### 6.4 Evidence coverage meter
Thin bar, `--accent` fill on `--hairline-soft` track. Label in mono: `2 of 2 medicines linked`. If any unlinked → label turns `--warn` and reads `1 of 2 linked · 1 missing context`.

### 6.5 Sign bar (sticky, the one elevated element)
Left: shield glyph + "AI-staged draft · Review required. You are in control." Right: `Save draft` (ghost) + `Approve & Sign` (solid `--accent`).

---

## 7. Signature element — the Safety Rail (build this well)

The right spine is where the whole design earns trust. Directions:

- When all checks pass, the rail is **quiet**: monochrome-green ticks, muted timestamps, low visual weight. Calm = safe.
- When something fails, **only that row lights** (amber/severe) and gains weight; the rest stays calm. The doctor's eye goes straight to the problem with zero hunting.
- **Acknowledgment is a gate, not a block.** Per the safety rule, the tool never prevents signing. So:
  ```
  Approve & Sign is ALWAYS enabled.
  If unacknowledged warnings exist and the doctor clicks it →
     open an acknowledgment sheet listing each warning, each with [Acknowledge] + reason.
     The doctor satisfies the gate by acknowledging (logged to safety_events),
     NEVER by the app changing the prescription.
  Once acknowledged → Approve & Sign proceeds → lock + PDF + audit.
  ```
- Every acknowledgment writes who / when / which warning / reason. The rail visibly reflects it (row → "Acknowledged by …").

This is the product's honesty made visual: it warns as loudly as needed, then hands the decision to the doctor and records it.

---

## 8. Copy voice

Plain, active, specific. The interface's voice, not a person's. No apologies.

```
  Good:  "Dose above usual range. Max 1000 mg per dose; this is 1300 mg. Reduce or acknowledge."
  Bad:   "Warning! Something may be wrong with the dosage."

  Good:  "Not in safety database — verify manually."
  Bad:   "Unable to check this medication at this time, sorry."

  Good:  "Cough type not confirmed (dry or productive). Confirm before prescribing."   [matches reference]
  Bad:   "Missing information detected."
```

Buttons say what happens and keep the name through the flow: `Approve & Sign` → toast `Prescription signed`. `Acknowledge` → row shows `Acknowledged`.

---

## 9. Motion (minimal — extra motion reads as AI-generated)

```
  transcript line       fade + 4px rise on arrival (Mode 3 streaming)     150ms
  ai-filled field       --accent-weak wash → transparent                  1000ms once
  safety row state      cross-fade color + icon swap                      150ms
  acknowledgment sheet  slide up from sign bar                            200ms
```
Nothing else animates. Respect `prefers-reduced-motion`: drop the rises/washes, keep instant state changes.

---

## 10. Quality floor (non-negotiable)

- WCAG AA contrast on all text and safety colors.
- **Safety state never conveyed by color alone** — always icon + text label (a red row also reads "SEVERE"). Colorblind doctors must read every state.
- Visible keyboard focus: 2px `--accent` ring, offset.
- Full keyboard operability (it's a data-entry tool doctors use fast).
- Responsive to mobile; safety state always visible, never collapsed away.
- Tabular mono figures so dose columns align.

---

## 11. Fonts to load

```
IBM Plex Sans — 400, 500, 600
IBM Plex Mono — 400, 500
Source: Google Fonts. Subset latin. Fallbacks: Plex Sans → system-ui, sans-serif;
Plex Mono → ui-monospace, "SFMono-Regular", monospace.
```
