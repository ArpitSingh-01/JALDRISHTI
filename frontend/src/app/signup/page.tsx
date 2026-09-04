"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";

export default function SignupPage() {
  const router = useRouter();
  const [displayName, setDisplayName] = useState("");
  const [org, setOrg] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
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
          maxWidth: "28rem",
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
            Register Official / Agency Account (Dam Safety Act 2021)
          </p>
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
          <div>
            <label className="stat-label" htmlFor="signup-name">
              Officer Name / Title
            </label>
            <input
              id="signup-name"
              type="text"
              required
              placeholder="Dr. S. Sharma, Executive Engineer"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
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
            <label className="stat-label" htmlFor="signup-org">
              Organisation / Authority
            </label>
            <input
              id="signup-org"
              type="text"
              required
              placeholder="CWC / SDMA / THDC India Ltd"
              value={org}
              onChange={(e) => setOrg(e.target.value)}
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
            <label className="stat-label" htmlFor="signup-email">
              Official Email
            </label>
            <input
              id="signup-email"
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
            <label className="stat-label" htmlFor="signup-password">
              Password
            </label>
            <input
              id="signup-password"
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
              Create Account & Enter Console →
            </Button>
          </div>
        </form>

        <div style={{ marginTop: "var(--space-lg)", textAlign: "center", fontSize: "var(--text-xs)", color: "var(--color-ink-2)" }}>
          <span>Already registered? </span>
          <Link href="/login" style={{ color: "var(--color-navy)", fontWeight: "var(--weight-bold)" }}>
            Sign In
          </Link>
        </div>
      </div>
    </div>
  );
}
