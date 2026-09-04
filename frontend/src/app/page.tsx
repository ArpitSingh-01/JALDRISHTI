import React from "react";
import Link from "next/link";
import { Navbar } from "@/components/landing/Navbar";
import { Footer } from "@/components/landing/Footer";
import { Button } from "@/components/ui/Button";
import { DisclaimerBlock } from "@/components/shared/DisclaimerBlock";
import {
  ARRIVALS_RAMP_DEMO,
  SCENARIOS_PREVIEW,
  VALIDATION_STEPS_PREVIEW,
} from "./landing-data";

export default function LandingPage() {
  return (
    <div className="landing-wrapper" data-register="landing">
      <Navbar />

      <main id="main-content">
        {/* 1 · Hero Section */}
        <section className="hero-section" aria-labelledby="hero-heading">
          <div className="page-container hero-grid">
            <div className="hero-content">
              <div className="hero-title-group">
                <span className="hero-deva" lang="hi">जलदृष्टि</span>
                <h1 id="hero-heading" className="hero-title">
                  JALDRISHTI
                </h1>
              </div>

              <p className="hero-tagline prose">
                Dam-break & river-blockage flood simulation that tells you{" "}
                <strong>who has to move, and when.</strong>
              </p>

              <div className="hero-ctas">
                <Button variant="primary" href="/runs" size="lg">
                  Open Simulation Console
                </Button>
                <Button variant="secondary" href="/scenarios" size="lg">
                  Explore Study Areas
                </Button>
              </div>

              <div className="hero-meta-row" style={{ marginTop: "var(--space-lg)" }}>
                <span className="stat-label">
                  Smart India Hackathon 2026 · PS 26161 · NTRO Track
                </span>
              </div>
            </div>

            <div className="hero-visual-card">
              <div className="hero-isochrone-preview">
                <div className="isochrone-sample-map">
                  {ARRIVALS_RAMP_DEMO.map((band, idx) => (
                    <div key={idx} className="isochrone-bar-row">
                      <div
                        className="isochrone-bar-fill num"
                        style={{
                          backgroundColor: band.colour,
                          width: `${band.widthPct}%`,
                        }}
                      >
                        {band.label}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <p className="hero-visual-caption">
                Simulated Tehri flood front advance (isochrone bands: 0–15 min to &gt;120 min).
                Output rendered from 2D shallow-water solver.
              </p>
            </div>
          </div>
        </section>

        {/* 2 · The Differentiator, Stated (§1.2) */}
        <section className="differentiator-section" aria-labelledby="diff-heading">
          <div className="page-container">
            <div className="differentiator-box">
              <div className="differentiator-header">
                <span className="differentiator-tag">THE DIFFERENTIATOR</span>
                <span className="stat-label">WHY THIS IS NOT JUST A BLUE BLOB</span>
              </div>

              <blockquote className="differentiator-quote">
                &ldquo;Water reaches this settlement in <strong>47 minutes</strong>; about{" "}
                <strong>12,000 people</strong> must evacuate.&rdquo;
              </blockquote>

              <p className="differentiator-explainer prose">
                Every competing tool renders inundation extent as an undifferentiated polygon.
                In a crisis, a district disaster officer needs <strong>arrival time</strong> and{" "}
                <strong>population exposure</strong>. JALDRISHTI calculates the flood front
                advance and cross-references settlements at risk to produce immediate,
                decision-ready evacuation timetables.
              </p>
            </div>
          </div>
        </section>

        {/* 3 · The Three Scenarios Triptych */}
        <section className="section" aria-labelledby="scenarios-heading">
          <div className="page-container">
            <div style={{ marginBottom: "var(--space-xl)" }}>
              <span className="stat-label">STUDY AREAS & EXPERIMENTS</span>
              <h2 id="scenarios-heading" style={{ fontSize: "var(--text-3xl)", marginTop: "var(--space-2xs)" }}>
                Three Rigorously Framed Scenarios
              </h2>
            </div>

            <div className="grid-auto">
              {SCENARIOS_PREVIEW.map((item) => (
                <div key={item.key} className="scenario-card">
                  <div>
                    <div className="scenario-card-header">
                      <span className="scenario-kind-badge">{item.kindLabel}</span>
                      <span className="stat-label num">{item.crs}</span>
                    </div>
                    <h3 className="scenario-card-title">{item.title}</h3>
                    <p className="scenario-card-desc">{item.purpose}</p>
                  </div>

                  <div style={{ paddingTop: "var(--space-md)", borderTop: "var(--rule-hairline) solid var(--color-rule)" }}>
                    <Button variant="secondary" href={`/scenarios/${item.key}`} size="sm">
                      Configure Failure Spec →
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* 4 · Validation Ladder Strip */}
        <section className="validation-strip" aria-labelledby="validation-heading">
          <div className="page-container validation-strip-grid">
            <div>
              <span className="stat-label" style={{ color: "var(--color-saffron)" }}>
                RIGOROUS VERIFICATION
              </span>
              <h2 id="validation-heading" className="validation-strip-title">
                Validated Against Field Data & Analytical Benchmarks
              </h2>
              <p className="validation-strip-desc prose">
                We do not ask jurors to take our hydrodynamics on faith. JALDRISHTI is verified
                across a five-rung ladder — from machine-precision lake-at-rest tests to the
                historic 1959 Malpasset dam collapse.
              </p>
              <div style={{ marginTop: "var(--space-lg)" }}>
                <Button variant="primary" href="/validation" size="md">
                  View Full Validation Ladder & Errors →
                </Button>
              </div>
            </div>

            <div className="validation-ladder-mini">
              <span className="stat-label" style={{ color: "rgba(255,255,255,0.7)" }}>
                THE 5-RUNG VALIDATION LADDER
              </span>
              {VALIDATION_STEPS_PREVIEW.map((step, idx) => (
                <div key={idx} className="ladder-step-mini">
                  <span>{step.name}</span>
                  <span className="num" style={{ color: "var(--color-saffron)" }}>
                    {step.metric}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* 5 · Statutory Framing */}
        <section className="section" aria-labelledby="statutory-heading">
          <div className="page-container">
            <span className="stat-label">LEGAL & REGULATORY GROUNDING</span>
            <h2 id="statutory-heading" style={{ fontSize: "var(--text-3xl)", marginTop: "var(--space-2xs)" }}>
              Built for Statutory Compliance
            </h2>
            <p className="prose" style={{ marginTop: "var(--space-xs)", color: "var(--color-ink-2)" }}>
              Dam-break inundation modelling in India is not an academic exercise — it is a
              statutory mandate for dam owners and district magistrates.
            </p>

            <div className="statutory-grid">
              <div className="statutory-card">
                <h3 className="statutory-card-title">Dam Safety Act, 2021</h3>
                <p className="statutory-card-desc">
                  Mandates comprehensive dam break studies and Emergency Action Plans (EAPs)
                  for all specified large dams in India.
                </p>
              </div>
              <div className="statutory-card">
                <h3 className="statutory-card-title">CWC Inundation Guidelines</h3>
                <p className="statutory-card-desc">
                  Central Water Commission standards for preparing downstream inundation maps
                  and hazard zone classifications.
                </p>
              </div>
              <div className="statutory-card">
                <h3 className="statutory-card-title">NDMA GLOF & Landslide Guidelines</h3>
                <p className="statutory-card-desc">
                  Protocols for natural dam formations, flash floods, and glacial lake outburst
                  early action.
                </p>
              </div>
              <div className="statutory-card">
                <h3 className="statutory-card-title">Sendai Framework Priority 4</h3>
                <p className="statutory-card-desc">
                  Enhancing disaster preparedness for effective response and &ldquo;Build Back Better&rdquo;
                  in recovery.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* 6 · Honesty Up Front */}
        <section className="section" style={{ backgroundColor: "var(--color-paper-2)", borderTop: "var(--rule-hairline) solid var(--color-rule)" }}>
          <div className="page-container">
            <div style={{ marginBottom: "var(--space-lg)" }}>
              <span className="stat-label">DEFENSIBLE DISCLOSURE</span>
              <h2 style={{ fontSize: "var(--text-2xl)", marginTop: "var(--space-2xs)" }}>
                What This Simulation Is — and What It Is Not
              </h2>
            </div>

            <DisclaimerBlock />
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}
