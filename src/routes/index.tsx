import { createFileRoute, Link } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { KeyLogo } from "@/components/keyboard/KeyLogo";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Stroke — AI dev studio for Roblox & code" },
      { name: "description", content: "Stroke is an all-in-one AI coding agent, tuned for AAA Roblox Studio engineering." },
      { property: "og:title", content: "Stroke — AI dev studio for Roblox & code" },
      { property: "og:description", content: "All-in-one AI coding agent, tuned for AAA Roblox Studio engineering." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Index,
});

function Index() {
  return (
    <main className="grid-bg flex min-h-screen flex-col items-center justify-center bg-background px-6 text-center">
      <KeyLogo size="lg" />
      <h1 className="mt-8 text-5xl font-bold tracking-tight md:text-7xl">Stroke</h1>
      <p className="mt-4 max-w-md text-muted-foreground">
        The all-in-one AI coding agent. Built for AAA Roblox Studio work — no placeholder assets.
      </p>
      <Button asChild size="lg" className="mt-10 shadow-glow font-mono">
        <Link to="/auth">Launch Stroke →</Link>
      </Button>
    </main>
  );
}
