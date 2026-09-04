# Antigravity build brief — JALDRISHTI frontend

You are building the frontend for **JALDRISHTI**, a dam-break flood simulation
platform for humanitarian disaster response (Smart India Hackathon 2026, Problem
Statement 26161, NTRO). The backend already exists and is tested; you are building
the web application that sits on top of it.

---

## The one rule that matters most

**`frontend.md` (at the repo root) is the single source of truth for this build.**
It was written by the backend author, who holds the full picture. It contains the
design system, every page, the exact backend data contract (real field names,
copied from live source), the API surface, the Supabase schema, the map
architecture, and the honesty rules that make this product defensible.

Read `frontend.md` in full before doing anything else. Read `frontend/design/
tokens.css` alongside it — that is the machine-readable half of the design system
(the OKLCH palette, type, spacing, motion, ramp mirror). Every detail you need is
in those two files. **Where this brief and `frontend.md` seem to differ, follow
`frontend.md`.**

Do not invent field names, endpoints, colours, or numbers. If `frontend.md` does
not name a field, the data does not exist — build against what is specified, not
what would be convenient.

---

## Workflow — plan first, code only after review

This is a hard gate:

1. **Produce an implementation plan and stop.** Do not write application code
   yet. The plan goes back to the backend author (via the human) for review.
2. The plan must cover, at minimum:
   - The exact stack and versions (Next.js App Router + deck.gl are decided; name
     the rest — state, data-fetching, motion, chart lib, component approach).
   - The file/folder structure you will create.
   - The 11 routes from `frontend.md §3`, and which you build in what order
     (follow the recommended order in `frontend.md §15` unless you have a reason).
   - How you wire `frontend/design/tokens.css` and the four fonts.
   - The TypeScript types for the backend contract (`frontend.md §6.2`) — the
     `ScenarioSummary.to_dict()` shape is the interface; type it exactly.
   - The mock-fixture layer (`frontend.md §12`) and the swappable API client
     (`frontend.md §7`) — the real `api/` does not exist yet, so you build against
     mocks and swap the base URL later.
   - The Supabase schema and RLS (`frontend.md §8`).
   - How you will verify the mobile floor (320/375/414/768 px) and both visual
     registers.
   - Anything in `frontend.md` you think is wrong, risky, or underspecified —
     raise it in the plan rather than silently working around it.
3. **Wait for approval of the plan before writing code.** After approval, build in
   the reviewed order. If the plan changes materially mid-build, surface it.

The reviewer is a backend engineer, not a designer — write the plan so it can be
checked against the data contract and the honesty rules, not just admired.

---

## Division of labour — stay in your lane

- **Yours:** all frontend scaffolding, UI, components, styling, routing, Supabase
  wiring, the mock/API client, deck.gl integration, responsive and accessibility
  work. The full application surface described in `frontend.md`.
- **Not yours:** the numerics, physics, solver, validation, and the backend
  `analysis`/`export`/`api` Python. Those belong to the backend author and are
  handled separately. If you need a backend field or endpoint that doesn't exist
  yet, **note it in the plan as a dependency** — do not implement backend logic or
  fake physics to fill the gap. Build against the mock fixtures instead.

---

## The Hallmark design skill

Use the **Hallmark** design skill for all design work. You may install it from:

**https://github.com/Nutlope/hallmark**

Hallmark is an anti-AI-slop design skill; it enforces structural variety, locked
design tokens, honest copy (no invented metrics), no re-drawn browser/phone
chrome, no italic headings, a mobile floor, and a pre-emit self-critique. Its
rules and the design decisions already made in `frontend.md`/`tokens.css` are
aligned on purpose — the theme is **"Tricolour Instrument," a custom Hallmark
theme** (the Indian flag palette tuned into OKLCH). Follow both.

If Hallmark cannot be installed or gets in the way, proceed without it — but then
you must carry the quality yourself: obey every rule in `frontend.md §2`
(design-system laws), `§11` (honesty UI), `§13` (accessibility), and `§14`
(traps). The anti-slop discipline is not optional; the skill is just the
convenient way to enforce it.

---

## Non-negotiables (all detailed in `frontend.md` — do not deviate)

These are the ones that will sink the product if you get them wrong. They are
correctness issues, not preferences:

1. **The differentiator is arrival time + exposure, not the inundation map.** Build
   the console around the `headline` sentence and the settlements-at-risk table
   (`frontend.md §1.2, §4.8`). Arrival is the default map layer.
2. **`null` and `-1` mean "not reached," never "0"** (`§6.3, §6.8`).
3. **Headline area = `flooded_area_km2` (new flooding), not `total_wetted_area_km2`**
   (`§6.3`).
4. **Exposure headline = `reported_population` (2 sig figs), not `total_population`**
   (`§6.7`).
5. **Damage is always a range, always flagged not-presentable-as-fact** (`§6.7`).
6. **Hazard and arrival ramps are generated, off the brand palette, never
   harmonised toward saffron** (`§2.2, §6.5, §6.6`). Import them from
   `frontend/src/lib/ramps.generated.ts` (the backend generates this file; a CI
   check fails the build if it drifts).
7. **Saffron is never a text colour and never carries light text; the primary
   button is saffron with a navy label** (`§2.1`).
8. **The time control is "front advance (from arrival time)," never "simulation
   playback"** — there are no per-timestep rasters (`§9.3`).
9. **Never imply Delft3D was run.** Render `SOLVER_ATTRIBUTION` and
   `MODEL_DISCLAIMER` verbatim from the backend (`§6.9`).
10. **No invented metrics, testimonials, or logos anywhere** (`§14.1`, Hallmark).
11. **Mobile floor 320/375/414/768 px, no horizontal scroll** (`§14.13`).
12. **Heavy rasters are not stored in Supabase** — free tier; metadata only
    (`§8`).
13. **The honesty UI (`§11`) is a graded feature, not polish.** The
    presentable-as-fact badge, the achromatic "unverified" treatment, the
    limitations list, and the verbatim disclaimer must all be built.

---

## Environment notes

- Database: **Supabase, free tier.** Schema and RLS in `frontend.md §8`.
- Colours: Indian flag — **saffron / white / green / navy** — tuned into OKLCH in
  `frontend/design/tokens.css`. Minimal yet professional; the user is open to
  animation, motion graphics, and morphism used with discipline (`§2.5`) — a
  single morphism signature (frosted-glass HUD over the map), meaningful motion,
  no decoration competing with the numbers.
- Framework: Next.js (App Router) + deck.gl. Pick the rest and justify it in the
  plan.

---

## Deliverable of this first step

**An implementation plan, and nothing else yet.** Send it back for review. After
it is approved, build in the reviewed order (`frontend.md §15`), starting with the
design system and the mock layer so the whole UI can be built and demoed before
the real API exists.
