import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { KeyLogo } from "@/components/keyboard/KeyLogo";
import { loadIngest } from "@/lib/keyboard-store";

export const Route = createFileRoute("/_authenticated/boot")({
  head: () => ({
    meta: [
      { title: "Initializing — Stroke" },
      { name: "description", content: "Stroke is verifying backend connectivity." },
    ],
  }),
  component: Boot,
});

function Boot() {
  const navigate = useNavigate();
  const [statusText, setStatusText] = useState("Connecting to Stroke FastAPI engine…");
  const [attempts, setAttempts] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function checkBackend() {
      try {
        setStatusText("Probing backend health at /api/health…");
        const res = await fetch("/api/health");
        if (res.ok) {
          const health = await res.json();
          if (cancelled) return;
          setStatusText(
            `Backend connected (${health.service} v${health.version}). Opening matrix operations…`,
          );
          setTimeout(() => {
            if (!cancelled) navigate({ to: "/chat", replace: true });
          }, 400);
          return;
        }
      } catch {
        // Retry
      }

      if (cancelled) return;
      setAttempts((a) => a + 1);
      if (attempts > 5) {
        setErrorMsg(
          "FastAPI backend not detected at localhost:8501. Start `python main.py` or `python desktop.py`.",
        );
        setStatusText("Backend offline — retry in progress…");
      }
    }

    const timer = setInterval(checkBackend, 1000);
    checkBackend();

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [navigate, attempts]);

  const ingest = loadIngest();

  return (
    <main className="grid-bg flex min-h-screen flex-col items-center justify-center bg-background px-6">
      <KeyLogo size="lg" />
      <div className="mt-10 w-full max-w-md text-center">
        <div className="h-2 overflow-hidden rounded-full bg-muted">
          <div className="bg-glow animate-shimmer h-full rounded-full shadow-glow transition-all w-full" />
        </div>
        <div className="mt-4 font-mono text-xs text-foreground">{statusText}</div>
        {errorMsg && <p className="mt-2 font-mono text-xs text-destructive">{errorMsg}</p>}
        <p className="mt-2 font-mono text-xs text-muted-foreground">
          Health check attempt #{attempts + 1}{" "}
          {ingest ? `· ${ingest.files} files from ${ingest.name}` : ""}
        </p>
      </div>
    </main>
  );
}
