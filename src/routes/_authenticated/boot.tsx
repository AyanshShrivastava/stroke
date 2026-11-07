import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { KeyLogo } from "@/components/keyboard/KeyLogo";
import { hasCache, writeCache, loadIngest } from "@/lib/keyboard-store";

export const Route = createFileRoute("/_authenticated/boot")({
  head: () => ({ meta: [{ title: "Initializing — Stroke" }, { name: "description", content: "Stroke is warming up its context." }] }),
  component: Boot,
});

const STAGES = [
  "Creating sandboxed workspace…",
  "Scanning Roblox asset hierarchy…",
  "Tracking nested instances & attachments…",
  "Extracting ParticleEmitter layers…",
  "Mapping TweenService easing curves…",
  "Indexing ColorSequence keypoints…",
  "Converting place map & lighting to text…",
  "Pumping 10-pack VFX database through context…",
  "Writing .stroke_cache…",
];

function Boot() {
  const navigate = useNavigate();
  const [pct, setPct] = useState(0);
  const [pass, setPass] = useState(0);

  useEffect(() => {
    if (hasCache()) { navigate({ to: "/chat", replace: true }); return; }
    const t = setInterval(() => {
      setPct((p) => {
        const n = Math.min(100, p + Math.random() * 4 + 1);
        if (n >= 100) {
          clearInterval(t);
          writeCache();
          setTimeout(() => navigate({ to: "/chat", replace: true }), 500);
        }
        return n;
      });
      setPass((x) => x + Math.floor(Math.random() * 9 + 3));
    }, 120);
    return () => clearInterval(t);
  }, [navigate]);

  const stage = STAGES[Math.min(STAGES.length - 1, Math.floor((pct / 100) * STAGES.length))];
  const ingest = loadIngest();

  return (
    <main className="grid-bg flex min-h-screen flex-col items-center justify-center bg-background px-6">
      <KeyLogo size="lg" />
      <div className="mt-10 w-full max-w-md">
        <div className="h-2 overflow-hidden rounded-full bg-muted">
          <div className="bg-glow animate-shimmer h-full rounded-full shadow-glow transition-all" style={{ width: `${pct}%` }} />
        </div>
        <div className="mt-4 flex justify-between font-mono text-xs text-muted-foreground">
          <span className="text-foreground">{stage}</span>
          <span>{Math.floor(pct)}%</span>
        </div>
        <p className="mt-2 font-mono text-xs text-muted-foreground">
          micro-training pass {pass} {ingest ? `· ${ingest.files} files from ${ingest.name}` : ""}
        </p>
      </div>
    </main>
  );
}
