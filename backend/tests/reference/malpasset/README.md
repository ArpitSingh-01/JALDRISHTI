# Malpasset 1959 — validation reference data

Field and laboratory observations for **Scenario A**, the validation case in `PLAN.md` §7.
This is the dataset that turns our solver from an animation into a validated model, so
treat these files as load-bearing.

## The event

The Malpasset arch dam on the Reyran river, ~12 km upstream of Fréjus (Var, France),
failed on **2 December 1959**. Maximum height 66.5 m, crest length 223 m, storage
~55 × 10⁶ m³. 421 people died. It is the most-used real-scale benchmark in
shallow-water modelling because — uniquely for a real dam break — three independent
families of observation survive.

## The three datasets

| File | What | n | Quantity |
|---|---|---|---|
| `police_survey_p1_p17.csv` | High-water marks surveyed by police after the flood | 17 | max water-surface **elevation** (m) |
| `transformers_abc.csv` | Shutdown times of three electrical transformers destroyed by the wave | 3 | **arrival time** (s) |
| `gauges_g6_g14.csv` | Gauges on the LNH-EDF 1:400 physical scale model (1964) | 9 | arrival time (s) + max WS elevation (m) |

Police surveyed nearly 100 points in total; the 17 here are the standard published
validation subset. The physical model had 14 gauges, but G1–G5 sat inside the
reservoir, so only the nine downstream gauges are useful.

## Coordinate frame and datum — read before using

- **Planimetric frame:** the EDF *local* coordinate system of the Malpasset mesh,
  in metres. It is **not** UTM and **not** lat/lon. Every coordinate in these CSVs,
  in the TELEMAC case, and in the ANUGA `.tsh` meshes is in this same frame.
  Do all validation in this frame. Georeferencing to UTM 32N is a presentation
  step only, and the one public attempt at it
  (`stoiver/anuga_malpasset/make_utm_mesh.py`) is explicitly hand-tuned by eye —
  it carries a `REFINE_DEG` "visual refinement knob". Do not treat it as survey-grade.
- **Vertical datum:** the same one in which the initial reservoir level is
  **100.0 m**. Sea level in the domain sits near −0.2 m, so it is effectively m a.s.l.
- **Elevation, not depth.** `ws_obs_m` and `ws_lab_m` are water-surface *elevations*.
  The official TELEMAC case prints maximum *depth* at these same points. Add bed
  elevation before comparing, or you will be wrong by tens of metres.

## Case setup (all cross-checked across two independent sources)

| Parameter | Value |
|---|---|
| Initial reservoir free surface | **100.0 m** — set as `h = 100.0 − z_bed` on the reservoir side |
| Dam line | straight line (4701.183, 4143.407) → (4655.553, 4392.104) |
| Reservoir test | signed point-to-line distance > 0.001 m |
| Forced-dry patch | circle centre (4500, 5350), radius 200 m, `h = 0` |
| Downstream initial state | dry bed, zero velocity |
| Friction | Manning **n = 0.033** uniform (= Strickler K = 30) |
| Simulated duration | 4000 s |
| Boundaries | TELEMAC uses solid/slip everywhere; several published studies instead use free outflow at the sea boundary |
| Viscosity | 1 m² s⁻¹ constant; no Coriolis, no wind |

The initial condition is worth restating because it is trivially reimplementable:
a signed point-to-line distance test against the dam line, then `h = 100 − z`
upstream, dry downstream. That is the whole scenario.

## Provenance and cross-validation

Two fully independent sources agree:

1. **openTELEMAC** official validation case, `examples/telemac2d/malpasset/` —
   an executable EDF-authored case. Observation coordinates are hardcoded in
   `user_fortran/utimp_telemac2d.f`; the initial condition is in
   `user_fortran/distan.f` (subroutine `CORSUI`).
2. **Biscarini, Di Francesco, Ridolfi & Manciola (2016)**, "On the Simulation of
   Floods in a Narrow Bending Valley: The Malpasset Dam Break Case Study",
   *Water* **8**(11):545, doi:10.3390/w8110545, CC-BY — Tables 2, 3 and 4.

All nine gauge coordinates agree to **< 1.4 m** (pure decimal truncation).
Transformers B and C agree exactly. Transformer **A differs by 50 m**
(TELEMAC 5550 vs paper 5500) — one of the two is a transcription slip; the
discrepancy is small enough not to matter for a 100 s arrival time, but the
TELEMAC value is recorded in `x_telemac_m` so the choice stays visible.

Friction is independently confirmed three ways: TELEMAC `FRICTION COEFFICIENT : 30.`
with Strickler law, ANUGA `set_quantity('friction', 0.033)`, and Kim et al. (2014)
"Manning coefficient is specified at 0.033". 1/30 = 0.0333.

## Terrain

Not in this folder (large binaries; see `data/reference/`). Two independent sources:

- `stoiver/anuga_malpasset` — `malpasset_26000_merged.tsh` and
  `malpasset_46691_mesh.tsh`. ANUGA ASCII triangle mesh: vertex coordinates with
  elevation attributes, then triangle connectivity and boundary tags. Plain text,
  trivially parseable, already in the local frame. **Start here.**
- openTELEMAC `geo_malpasset-small.slf` (13,541 nodes / 26,000 triangles) and
  `geo_malpasset-large.slf` (53,081 nodes / 104,000 triangles). Selafin binary.
  The repo also ships TELEMAC's own computed results as `f2d_malpasset-*.slf`,
  which lets us do a solver-to-solver comparison against an industry-standard
  code — directly useful for the Delft3D position in `PLAN.md` §6.

Note the 26,000-triangle count matches between the two, so the ANUGA mesh derives
from the same EDF dataset.

## Caveats to state openly on the slide

- **The terrain predates the event.** Bed elevations were digitised from **1931
  maps**; the field data were collected after a flood that violently reshaped the
  valley. Some of the model–observation mismatch is terrain error, not solver error.
- **The transformer times are inferred, not measured.** They are electrical
  shutdown times. Only transformer A (valley bottom, just below the dam) is a clean
  arrival time; for B and C the shutdown lies somewhere between arrival and peak,
  so they are upper bounds. Validate on relative times (B−A = 1140 s, C−A = 1320 s).
- **No uncertainty is published** for the police high-water marks.
- **The 1:400 model is a model.** G6–G14 are laboratory truth, not field truth.

## What "good" looks like

From Kim, Sanders et al. (2014), *Adv. Water Resour.* **68**:42–61 (Table 7), which
tested Cartesian, triangular and mixed meshes from coarse to a 2.07-million-cell
ultra-fine grid: reported L1 errors span roughly **0.7–2.9 m** on maximum water
height and **15–225 s** on arrival time. Even their finest grid lands ~2.8 m off on
maximum water height.

This is the single most useful number in this folder. If our solver reaches ~2–3 m
L1 on max water level and tens of seconds on arrival time, it is performing at
published-literature quality — and we can say so with a citation. It also sets an
honest expectation: nobody matches Malpasset to the metre, and a jury member who
knows the case will trust us more for saying that than for claiming we nailed it.

## Verified against the terrain (2026-08-28)

Parsed `malpasset_46691_mesh.tsh` (24,173 vertices, 1 elevation attribute) and
sampled the nearest mesh vertex at all 26 observation points:

- Domain spans **17,227 m × 9,181 m**, matching the documented ~17 km × 9 km.
- Bed elevation ranges **−20.97 m to +111.43 m** — the 100 m reservoir level sits
  below the highest terrain, and the sea floor is below zero. The vertical datum
  is therefore consistent with the 100 m initial condition. Independent confirmation.
- **All 26 points fall inside the mesh**, with the nearest vertex 7–36 m away
  (element size is 8.5–156 m, so this is expected).
- At all nine channel gauges G6–G14, `ws_lab − z_bed` is **positive, 4.8–42.9 m** —
  i.e. physically sensible water depths.
- At the police bank marks, `ws_obs − z_bed` is small and positive for the
  mid/downstream points (0.7–7.8 m), which is exactly right for a high-water mark
  left on a bank. Near the dam (P1, P2, P4) the gap is large (23–49 m) because
  those points sit in the steep gorge where the nearest vertex can lie well down
  the valley wall.

**Sampling guidance that follows from this.** Three bank marks (P13 −2.31 m,
P14 −0.63 m, P16 −0.43 m) sit marginally *below* the interpolated bed. That is
terrain-interpolation error at the wet/dry edge, not bad data — but it means a
single-nearest-cell sample will report those points permanently dry and generate a
spurious large error. Sample bank points as the **maximum over cells within roughly
one cell radius**, and say so in the methods. The channel gauges have no such
problem and can be sampled directly.

## Sources

- Biscarini, C.; Di Francesco, S.; Ridolfi, E.; Manciola, P. (2016). *Water* 8(11):545. doi:10.3390/w8110545 (CC-BY) — **the observation tables**.
- openTELEMAC, `examples/telemac2d/malpasset/` — executable case, EDF-authored.
- Hervouet, J.-M. (2007). *Hydrodynamics of Free Surface Flows: Modelling with the Finite Element Method*. Wiley, pp. 281–288 — authoritative case description.
- Hervouet, J.-M.; Petitjean, A. (1999). Malpasset dam-break revisited with two-dimensional computations. *J. Hydraulic Research* 37(6).
- Kim, B.; Sanders, B.F.; et al. (2014). Mesh type tradeoffs in 2D hydrodynamic modeling of flooding with a Godunov-based flow solver. *Adv. Water Resour.* 68:42–61 — error benchmarks.
- Kim, B.; Kim, T.; Kim, J.; Han, K. (2014). *J. Vibroengineering* 16(3) — independent confirmation of setup.
