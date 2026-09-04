import React from "react";
import Link from "next/link";
import { STATUTORY_CITATIONS, MODEL_DISCLAIMER } from "@/lib/constants";

export const Footer: React.FC = () => {
  return (
    <footer className="landing-footer">
      <div className="page-container footer-container">
        <div className="footer-top-grid">
          <div className="footer-brand-col">
            <div className="brand-lockup">
              <span className="brand-deva" lang="hi">जलदृष्टि</span>
              <span className="brand-latin">JALDRISHTI</span>
            </div>
            <p className="footer-tagline prose-narrow">
              Dam-break & river-blockage hydrodynamic flood simulation for humanitarian
              action and emergency disaster relief.
            </p>
            <div className="footer-org-tag">
              <span>Smart India Hackathon 2026</span>
              <span className="bullet-sep">•</span>
              <span>PS 26161</span>
              <span className="bullet-sep">•</span>
              <span>NTRO</span>
            </div>
          </div>

          <div className="footer-links-col">
            <h4 className="footer-col-title">Navigation</h4>
            <ul className="footer-list">
              <li><Link href="/">Overview</Link></li>
              <li><Link href="/scenarios">Study Areas & Scenarios</Link></li>
              <li><Link href="/validation">Validation Ladder</Link></li>
              <li><Link href="/methodology">Physics & Numerics</Link></li>
              <li><Link href="/about">About & Citations</Link></li>
              <li><Link href="/runs">Simulation Console</Link></li>
            </ul>
          </div>

          <div className="footer-statutory-col">
            <h4 className="footer-col-title">Statutory Framing</h4>
            <ul className="footer-list">
              {STATUTORY_CITATIONS.map((cit, idx) => (
                <li key={idx} className="footer-statutory-item">
                  <span className="statutory-icon">§</span>
                  <span>{cit}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="footer-disclaimer-row">
          <p className="footer-disclaimer-text">
            <strong>Model Disclaimer:</strong> {MODEL_DISCLAIMER}
          </p>
        </div>

        <div className="footer-bottom-row">
          <p className="footer-copy">
            © 2026 JALDRISHTI Team. National Technical Research Organisation (NTRO) Track.
          </p>
          <div className="footer-bottom-links">
            <Link href="/methodology">Solver Attribution</Link>
            <Link href="/about">Data Provenance</Link>
          </div>
        </div>
      </div>
    </footer>
  );
};
