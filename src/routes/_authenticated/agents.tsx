import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/keyboard/AppShell";
import { ParallelAgentManager } from "@/components/keyboard/ParallelAgentManager";

export const Route = createFileRoute("/_authenticated/agents")({
  head: () => ({
    meta: [
      { title: "Parallel Multi-Agent System — Stroke" },
      {
        name: "description",
        content:
          "Collaborative multi-agent engineering: Researcher, Planner, Developer, Tester, Reviewer, and Debugger.",
      },
    ],
  }),
  component: AgentsPage,
});

function AgentsPage() {
  return (
    <AppShell>
      <div className="flex h-full flex-col overflow-y-auto bg-background text-foreground">
        <ParallelAgentManager />
      </div>
    </AppShell>
  );
}
