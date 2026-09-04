"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/Button";
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
    <header className="landing-nav-header">
      <div className="page-container nav-container">
        <Link href="/" className="nav-brand" aria-label="JALDRISHTI Home">
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
  );
};
