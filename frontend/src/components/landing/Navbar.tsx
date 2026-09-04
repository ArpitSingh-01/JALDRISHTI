"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Emblem } from "@/components/brand/Emblem";
import { cn } from "@/lib/utils";

export const Navbar: React.FC = () => {
  const pathname = usePathname();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const navLinks = [
    { href: "/scenarios", label: "Scenarios" },
    { href: "/validation", label: "Validation" },
    { href: "/methodology", label: "Methodology" },
    { href: "/about", label: "About & Legal" },
  ];

  return (
    <>
      {/*
        Government-portal masthead strip. Names the programme and the
        organisation the problem statement belongs to. It deliberately does
        NOT claim to BE a Government of India website — that would be
        improper under the State Emblem of India (Prohibition of Improper
        Use) Act, 2005, and dishonest. The visual language is portal-
        formal; the words are true.
      */}
      <div className="gov-strip">
        <div className="page-container gov-strip-inner">
          <span className="gov-strip-left">
            <span className="gov-strip-deva" lang="hi">जलदृष्टि</span>
            <span className="gov-strip-sep" aria-hidden="true">·</span>
            <span>Smart India Hackathon 2026</span>
            <span className="gov-strip-sep" aria-hidden="true">·</span>
            <span>Problem Statement 26161</span>
          </span>
          <span className="gov-strip-right">
            Organisation: National Technical Research Organisation
            <span className="gov-strip-sep" aria-hidden="true">·</span>
            Theme: Disaster Management
          </span>
        </div>
      </div>

      <header className="landing-nav-header">
        <a href="#main-content" className="skip-link">
          Skip to main content
        </a>
        <div className="page-container nav-container">
          <Link href="/" className="nav-brand" aria-label="JALDRISHTI Home">
            <Emblem size={42} label="" className="brand-emblem" />
            <div className="brand-lockup">
              <span className="brand-deva" lang="hi">जलदृष्टि</span>
              <span className="brand-latin">JALDRISHTI</span>
            </div>
            <span className="brand-badge">SIH 26161</span>
          </Link>

        <nav className="nav-links hide-mobile" aria-label="Main Navigation">
          {navLinks.map((link) => {
            const isActive = pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={cn("nav-link", isActive && "nav-link-active")}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>

        <div className="nav-actions hide-mobile">
          <Button variant="primary" href="/runs" size="sm">
            Open Console
          </Button>
        </div>

        <button
          type="button"
          className="nav-mobile-toggle hide-desktop"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          aria-expanded={mobileMenuOpen}
          aria-label="Toggle navigation menu"
        >
          <span className="toggle-bar" />
          <span className="toggle-bar" />
          <span className="toggle-bar" />
        </button>
      </div>

      {mobileMenuOpen && (
        <div className="nav-mobile-drawer hide-desktop">
          <nav className="nav-mobile-links">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="nav-mobile-link"
                onClick={() => setMobileMenuOpen(false)}
              >
                {link.label}
              </Link>
            ))}
            <div className="nav-mobile-action">
              <Button variant="primary" href="/runs" size="md">
                Open Console
              </Button>
            </div>
          </nav>
        </div>
      )}
    </header>
    </>
  );
};
