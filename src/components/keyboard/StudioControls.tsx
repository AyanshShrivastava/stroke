import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { BookOpen, ChevronRight, Cpu, FileKey, FolderOpen, Moon, Settings2, Sun, Unplug, Waves } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { KeyLogo } from "./KeyLogo";

type StudioContextValue = { model: string; setModel: (v: string) => void; dark: boolean; toggleTheme: () => void; openSettings: (tab?: string) => void; openDocs: () => void };
const StudioContext = createContext<StudioContextValue | null>(null);
export function useStudio() {
  const value = useContext(StudioContext);
  if (!value) throw new Error("StudioProvider is required");
  return value;
}
export function StudioProvider({ children }: { children: ReactNode }) {
  const [model, setModel] = useState("Llama 3.2 1B");
  const [dark, setDark] = useState(false);
  const [settings, setSettings] = useState(false);
  const [docs, setDocs] = useState(false);
  const [tab, setTab] = useState("models");
  const [provider, setProvider] = useState("local");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:7331/mcp");
  const [file, setFile] = useState("");
  const [key, setKey] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    const isDark = localStorage.getItem("stroke.theme") === "dark";
    setDark(isDark); document.documentElement.classList.toggle("dark", isDark);
    setEndpoint(localStorage.getItem("stroke.mcp.endpoint") || "http://127.0.0.1:7331/mcp");
  }, []);
  function toggleTheme() {
    const next = !dark; setDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("stroke.theme", next ? "dark" : "light");
  }
  function openSettings(next = "models") { setTab(next); setSaved(false); setSettings(true); }
  return <StudioContext.Provider value={{ model, setModel, dark, toggleTheme, openSettings, openDocs: () => setDocs(true) }}>
    {children}
    <Dialog open={settings} onOpenChange={(open) => { setSettings(open); if (!open) setKey(""); }}>
      <DialogContent className="settings-dialog max-h-[85dvh] max-w-2xl overflow-y-auto p-0">
        <DialogHeader className="border-b border-border px-7 py-6"><DialogTitle className="text-xl">Make Stroke yours</DialogTitle><DialogDescription>Models, connections, and your private workspace.</DialogDescription></DialogHeader>
        <div className="flex flex-col sm:flex-row">
          <nav aria-label="Settings sections" className="flex gap-1 border-b border-border bg-muted/40 p-3 sm:w-44 sm:flex-col sm:border-b-0 sm:border-r">
            {[{ id: "models", name: "AI models", icon: Cpu }, { id: "studio", name: "Roblox Studio", icon: Waves }, { id: "vault", name: "Credentials", icon: FileKey }].map(({ id, name, icon: Icon }) => <Button key={id} variant="ghost" className={`justify-start text-xs ${tab === id ? "bg-accent" : "text-muted-foreground"}`} onClick={() => { setTab(id); setSaved(false); }}><Icon />{name}</Button>)}
          </nav>
          <div className="min-w-0 flex-1 space-y-5 p-6">
            {tab === "models" && <>
              <div><h3 className="font-medium">Your AI engine</h3><p className="mt-1 text-xs leading-5 text-muted-foreground">The web companion currently uses placeholder replies. Model preferences do not connect an engine.</p></div>
              <div className="space-y-2"><Label>Provider</Label><Select value={provider} onValueChange={setProvider}><SelectTrigger aria-label="AI provider"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="local">Local GGUF</SelectItem><SelectItem value="openai">OpenAI · BYOK</SelectItem><SelectItem value="anthropic">Anthropic · BYOK</SelectItem></SelectContent></Select></div>
              <div className="space-y-2"><Label>Preferred model</Label><ModelSelector /></div>
              {provider === "local" ? <div className="space-y-2"><Label htmlFor="gguf">GGUF model file</Label><label htmlFor="gguf" className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed border-border p-4 text-sm"><FolderOpen className="h-5 w-5 text-muted-foreground" /><span className="min-w-0 break-all">{file || "Choose a .gguf file"}</span></label><Input id="gguf" type="file" accept=".gguf" className="sr-only" onChange={(e) => setFile(e.target.files?.[0]?.name || "")} /><p className="text-xs text-muted-foreground">Filename only. Inference requires the desktop app.</p></div> : <p className="text-sm text-muted-foreground">API connections are not enabled in this web companion. No key will be sent.</p>}
            </>}
            {tab === "studio" && <><div className="flex items-center justify-between"><h3 className="font-medium">Roblox Studio MCP</h3><span className="status-badge"><Unplug className="h-3 w-3" />Disconnected</span></div><div className="space-y-2"><Label htmlFor="mcp">Server endpoint</Label><Input id="mcp" type="url" value={endpoint} onChange={(e) => { setEndpoint(e.target.value); setSaved(false); }} /></div><p className="text-sm leading-6 text-muted-foreground">Live socket sync is available in the Stroke desktop app. This browser workspace does not open a local Studio connection.</p><Button onClick={() => { localStorage.setItem("stroke.mcp.endpoint", endpoint); setSaved(true); }}>Save endpoint</Button>{saved && <p role="status" className="text-xs text-success">Endpoint saved on this device. Not connected.</p>}</>}
            {tab === "vault" && <><h3 className="font-medium">Credentials vault</h3><div className="flex items-start gap-3 rounded-lg border border-border bg-muted/40 p-4"><FileKey className="mt-1 h-5 w-5 shrink-0" /><p className="text-sm leading-6 text-muted-foreground">The encrypted vault belongs to the desktop app. Keys entered here stay only in this open dialog and are cleared when it closes.</p></div><div className="space-y-2"><Label htmlFor="api-key">API key</Label><Input id="api-key" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="Not saved or transmitted" /></div><Button variant="outline" disabled={!key} onClick={() => setKey("")}>Clear key</Button></>}
          </div>
        </div>
        <div className="flex items-center gap-2 border-t border-border px-6 py-4 text-xs text-muted-foreground"><span className="h-1.5 w-1.5 rounded-full bg-aurora-blue" />Stroke web companion<span className="ml-auto">Private by design</span></div>
      </DialogContent>
    </Dialog>
    <Dialog open={docs} onOpenChange={setDocs}><DialogContent className="max-w-xl"><DialogHeader><DialogTitle>Stroke documentation</DialogTitle><DialogDescription>Your Roblox development workspace.</DialogDescription></DialogHeader><div className="space-y-5 text-sm leading-6"><section><h3 className="font-medium">Builder Core</h3><p className="text-muted-foreground">Choose a development mode and send a prompt. Replies in this web version are sample drafts, not live AI output.</p></section><section><h3 className="font-medium">Studio & diagnostics</h3><p className="text-muted-foreground">Local MCP, GGUF inference, compiler checks, and command execution require the desktop app. No successful check is displayed without a real result.</p></section><section><h3 className="font-medium">Archivist</h3><p className="text-muted-foreground">Signed-in chats stay on this device. Every 30 seconds, new decisions are compacted and synced to your Cloud account.</p></section><Button asChild variant="outline"><a href="https://github.com/AyanshShrivastava/stroke" target="_blank" rel="noreferrer">View project on GitHub<ChevronRight /></a></Button></div></DialogContent></Dialog>
  </StudioContext.Provider>;
}
export function ModelSelector({ compact = false }: { compact?: boolean }) {
  const { model, setModel } = useStudio();
  return <Select value={model} onValueChange={setModel}><SelectTrigger aria-label="Preferred AI model" className={compact ? "h-8 w-auto gap-2 border-0 bg-transparent px-2 text-xs shadow-none" : "w-full"}><Cpu className="h-3.5 w-3.5 text-muted-foreground" /><SelectValue /></SelectTrigger><SelectContent><SelectItem value="Llama 3.2 1B">Llama 3.2 1B</SelectItem><SelectItem value="Qwen 2.5 Coder">Qwen 2.5 Coder</SelectItem><SelectItem value="Custom GGUF">Custom GGUF</SelectItem></SelectContent></Select>;
}
export function StudioHeader({ menu }: { menu?: ReactNode }) {
  const { dark, toggleTheme, openSettings, openDocs } = useStudio();
  return <header className="studio-header flex h-[72px] shrink-0 items-center gap-3 border-b border-border px-4 lg:px-7">
    {menu}<div className="flex items-center gap-2.5 md:hidden"><KeyLogo /><span className="text-lg font-semibold">Stroke</span></div>
    <div className="hidden items-center gap-2 text-xs text-muted-foreground md:flex"><span>Workspace</span><ChevronRight className="h-3 w-3" /><span className="text-foreground">Studio</span></div>
    <div className="ml-auto flex items-center gap-2 sm:gap-4">
      <Button variant="ghost" size="sm" className="connection-pill hidden rounded-full border border-border bg-card/70 text-muted-foreground sm:flex" onClick={() => openSettings("studio")}><span className="h-1.5 w-1.5 rounded-full bg-warning" />Studio disconnected</Button>
      <div className="hidden lg:block"><ModelSelector compact /></div>
      <div className="hidden h-5 w-px bg-border lg:block" />
      <Button variant="ghost" size="sm" className="hidden gap-1.5 text-muted-foreground sm:flex" onClick={openDocs}><BookOpen />Docs</Button>
      <Button variant="ghost" size="icon" aria-label="Open settings" title="Settings" onClick={() => openSettings()}><Settings2 /></Button>
      <Button variant="ghost" size="icon" aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} title={dark ? "Light mode" : "Dark mode"} onClick={toggleTheme}>{dark ? <Sun /> : <Moon />}</Button>
    </div>
  </header>;
}
