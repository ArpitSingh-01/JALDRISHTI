"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    // Simulates auth completion for mock/demo register
    setTimeout(() => {
      setIsLoading(false);
      router.push("/runs");
    }, 600);
  };

  return (
    <div className="landing-wrapper" data-register="landing" style={{ justifyContent: "center", alignItems: "center", minHeight: "100vh" }}>
      <div
        style={{
          width: "100%",
          maxWidth: "26rem",
          padding: "var(--space-2xl)",
          backgroundColor: "var(--color-paper-2)",
          border: "var(--rule-hairline) solid var(--color-rule-strong)",
          borderRadius: "var(--radius-lg)",
          boxShadow: "var(--shadow-2)",
        }}
      >
        <div style={{ textAlign: "center", marginBottom: "var(--space-xl)" }}>
          <Link href="/" className="brand-lockup" style={{ justifyContent: "center" }}>
            <span className="brand-deva" lang="hi" style={{ fontSize: "var(--text-2xl)" }}>जलदृष्टि</span>
            <span className="brand-latin" style={{ fontSize: "var(--text-xl)" }}>JALDRISHTI</span>
          </Link>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--color-ink-3)", marginTop: "var(--space-2xs)" }}>
            Disaster Management & Simulation Console
          </p>
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
          <div>
            <label className="stat-label" htmlFor="login-email">
              Official / Agency Email
            </label>
            <input
              id="login-email"
              type="email"
              required
              placeholder="officer@ndma.gov.in"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{
                width: "100%",
                padding: "var(--space-xs) var(--space-sm)",
                borderRadius: "var(--radius-sm)",
                border: "var(--rule-hairline) solid var(--color-rule-strong)",
                backgroundColor: "var(--color-paper)",
                color: "var(--color-ink)",
                fontFamily: "var(--font-body)",
                fontSize: "var(--text-sm)",
                marginTop: "var(--space-2xs)",
              }}
            />
          </div>

          <div>
            <label className="stat-label" htmlFor="login-password">
              Password
            </label>
            <input
              id="login-password"
              type="password"
              required
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{
                width: "100%",
                padding: "var(--space-xs) var(--space-sm)",
                borderRadius: "var(--radius-sm)",
                border: "var(--rule-hairline) solid var(--color-rule-strong)",
                backgroundColor: "var(--color-paper)",
                color: "var(--color-ink)",
                fontFamily: "var(--font-body)",
                fontSize: "var(--text-sm)",
                marginTop: "var(--space-2xs)",
              }}
            />
          </div>

          <div style={{ marginTop: "var(--space-xs)" }}>
            <Button
              variant="primary"
              size="lg"
              isLoading={isLoading}
              style={{ width: "100%" }}
            >
              Sign In to Console →
            </Button>
          </div>
        </form>

        <div style={{ marginTop: "var(--space-lg)", textAlign: "center", fontSize: "var(--text-xs)", color: "var(--color-ink-2)" }}>
          <span>Don&apos;t have an account? </span>
          <Link href="/signup" style={{ color: "var(--color-navy)", fontWeight: "var(--weight-bold)" }}>
            Register Agency Access
          </Link>
        </div>
      </div>
    </div>
  );
}
