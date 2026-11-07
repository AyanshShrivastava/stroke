import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Github, Server, FolderTree, CloudUpload } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AppShell, StorageMeter } from "@/components/keyboard/AppShell";
import { compactMessages, loadChats, saveChats, loadGithub, saveGithub, loadIngest, saveIngest, formatBytes, type Ingested } from "@/lib/keyboard-store";

export const Route = createFileRoute("/_authenticated/integrations")({
  head: () => ({ meta: [{ title: "Integrations — Stroke" }, { name: "description", content: "GitHub, MCP server, Roblox ingestion and storage." }] }),
  component: Integrations,
});

function Card({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return <section className="rounded-xl border border-border bg-card p-5"><h2 className="mb-4 flex items-center gap-2 font-semibold">{icon}{title}</h2>{children}</section>;
}

function Integrations() {
  const [gh, setGh] = useState({ pat: "", repo: "" });
  const [ingest, setIngest] = useState<Ingested>(null);
  useEffect(() => { setGh(loadGithub()); setIngest(loadIngest()); }, []);

  async function onFolder(files: FileList | null) {
    if (!files?.length) return;
    const ok = Array.from(files).filter((f) => /\.(lua|luau|rbxmx|rbxlx|json|txt|toml|md)$/i.test(f.name));
    let bytes = 0; const lines: string[] = [];
    for (const f of ok.slice(0, 400)) {
      bytes += f.size;
      const path = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
      const depth = path.split("/").length - 1;
      lines.push(`${"  ".repeat(depth)}${path.split("/").pop()} (${f.size}b)`);
    }
    const f0 = files[0] as File & { webkitRelativePath?: string };
    const name = (f0.webkitRelativePath || f0.name).split("/")[0] || "project";
    const v = { name, files: ok.length, bytes, map: lines.join("\n").slice(0, 200_000), at: Date.now() };
    saveIngest(v); setIngest(v);
    toast.success(`Ingested ${ok.length} files from ${name}`);
  }

  async function offload() {
    const chats = loadChats();
    const rows = chats.map((c) => ({ chat_id: c.id, content: compactMessages(c.messages) })).filter((r): r is { chat_id: string; content: string } => !!r.content);
    if (!rows.length) { toast("Nothing to offload yet"); return; }
    const { error } = await supabase.from("archive_notes").insert(rows);
    if (error) { toast.error("Offload failed"); return; }
    saveChats(chats.map((c) => ({ ...c, messages: c.messages.slice(-4), archivedUpTo: Math.min(c.archivedUpTo, 4) })));
    toast.success(`Offloaded ${rows.length} chats to Cloud and trimmed local history`);
  }

  return (
    <AppShell>
      <div className="overflow-y-auto p-4 md:p-8">
        <div className="mx-auto max-w-3xl space-y-5">
          <h1 className="text-3xl font-bold">Integrations</h1>
          <Card icon={<FolderTree className="h-4 w-4 text-primary" />} title="Roblox asset ingestion">
            <p className="mb-3 text-sm text-muted-foreground">Pick an exported Roblox project folder (.lua, .luau, .rbxmx, .rbxlx). Stroke maps the nested hierarchy into text context.</p>
            <input type="file" multiple onChange={(e) => onFolder(e.target.files)} {...{ webkitdirectory: "", directory: "" }} className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-secondary-foreground" />
            {ingest && <pre className="mt-4 max-h-48 overflow-auto rounded-md border border-border bg-background p-3 font-mono text-xs">{`${ingest.name} · ${ingest.files} files · ${formatBytes(ingest.bytes)}\n\n${ingest.map}`}</pre>}
          </Card>
          <Card icon={<Github className="h-4 w-4 text-primary" />} title="GitHub">
            <div className="grid gap-3">
              <div className="space-y-1"><Label htmlFor="pat">Personal access token</Label><Input id="pat" type="password" value={gh.pat} onChange={(e) => setGh({ ...gh, pat: e.target.value })} placeholder="ghp_…" /></div>
              <div className="space-y-1"><Label htmlFor="repo">Repository</Label><Input id="repo" value={gh.repo} onChange={(e) => setGh({ ...gh, repo: e.target.value })} placeholder="owner/repo" /></div>
              <div className="flex gap-2">
                <Button onClick={() => { saveGithub(gh); toast.success("Saved on this device"); }}>Save</Button>
                <Button variant="secondary" disabled={!gh.pat || !gh.repo} onClick={() => toast("Push is simulated in the browser version")}>Push version</Button>
              </div>
              <p className="text-xs text-muted-foreground">The token stays on this device only.</p>
            </div>
          </Card>
          <Card icon={<Server className="h-4 w-4 text-primary" />} title="Local MCP server">
            <div className="flex items-center gap-3 font-mono text-sm"><span className="h-2 w-2 rounded-full bg-muted-foreground" /> localhost:7331 — available in the desktop build</div>
          </Card>
          <Card icon={<CloudUpload className="h-4 w-4 text-primary" />} title="Storage (1 GB cap)">
            <StorageMeter />
            <Button className="mt-3" variant="secondary" onClick={offload}>Offload old history to Cloud</Button>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
