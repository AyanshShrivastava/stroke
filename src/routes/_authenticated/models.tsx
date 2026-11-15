import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/keyboard/AppShell";
import { ModelsManager } from "@/components/keyboard/ModelsManager";
import { Cpu } from "lucide-react";

export const Route = createFileRoute("/_authenticated/models")({
  head: () => ({
    meta: [
      { title: "Models & BYOK Providers — Stroke" },
      {
        name: "description",
        content: "Manage AI providers, API keys, model selections, and neural reasoning effort.",
      },
    ],
  }),
  component: ModelsPage,
});

function ModelsPage() {
  return (
    <AppShell>
      <div className="flex h-full flex-col overflow-y-auto bg-background text-foreground">
        <div className="mx-auto w-full max-w-4xl p-6 md:p-8 space-y-6">
          <div className="flex items-center justify-between border-b border-border pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
                <Cpu className="h-5 w-5 text-primary" />
                AI Models & Providers
              </h1>
              <p className="mt-1 text-xs text-muted-foreground">
                Connect your API keys for Groq, Google Gemini, OpenRouter, Anthropic, OpenAI, or
                Custom endpoints.
              </p>
            </div>
          </div>
          <ModelsManager />
        </div>
      </div>
    </AppShell>
  );
}
