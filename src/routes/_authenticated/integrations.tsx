import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Github,
  Server,
  FolderTree,
  Database,
  Sun,
  Moon,
  Laptop,
  Cpu,
  Brain,
  ShieldCheck,
  CheckCircle2,
  HardDrive,
  RefreshCw,
  Sliders,
  Download,
  Upload,
  Trash2,
  Key,
  Lock,
  AlertCircle,
  XCircle,
  ExternalLink,
  Eye,
  EyeOff,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AppShell } from "@/components/keyboard/AppShell";
import { ThemeSelector } from "@/components/keyboard/ThemeToggle";
import {
  loadGithub,
  saveGithub,
  loadIngest,
  saveIngest,
  formatBytes,
  loadUserPreferences,
  saveUserPreferences,
  AVAILABLE_MODELS,
  REASONING_LEVELS,
  type Ingested,
  fetchModelProviders,
  saveProviderCredential,
  deleteProviderCredential,
  testProviderConnection,
  fetchActiveModelConfig,
  saveActiveModelConfig,
  type ProviderStatusInfo,
  type ActiveModelConfig,
} from "@/lib/keyboard-store";
import {
  exportLocalDataJson,
  importLocalDataJson,
  idbClearAllChats,
  estimateStorage,
  type StorageDiagnostics,
} from "@/lib/idb-storage";

export const Route = createFileRoute("/_authenticated/integrations")({
  head: () => ({
    meta: [
      { title: "Settings — Stroke" },
      { name: "description", content: "Appearance, models, GitHub, MCP and workspace configuration." },
    ],
  }),
  component: Integrations,
});

type TabId = "appearance" | "models" | "workspaces" | "github" | "mcp" | "memory";

function Integrations() {
  const [activeTab, setActiveTab] = useState<TabId>("appearance");
  const [prefs, setPrefs] = useState(() => loadUserPreferences());
  const [gh, setGh] = useState({ pat: "", repo: "" });
  const [ghStatus, setGhStatus] = useState<{
    connected: boolean;
    username?: string;
    source?: string;
    is_environment_managed?: boolean;
    is_vault_managed?: boolean;
    rate_limit_remaining?: number | string;
  }>({ connected: false });
  const [mcpStatus, setMcpStatus] = useState<{
    active: boolean;
    toolsCount: number;
    message: string;
  }>({ active: false, toolsCount: 0, message: "Checking…" });
  const [memoryStats, setMemoryStats] = useState<{ count: number; total_bytes: number }>({
    count: 0,
    total_bytes: 0,
  });
  const [ingest, setIngest] = useState<Ingested>(null);
  const [indexStats, setIndexStats] = useState<{
    workspace_path?: string;
    project_name?: string;
    total_files: number;
    total_bytes: number;
    last_indexed_at?: number;
  }>({ total_files: 0, total_bytes: 0 });
  const [isIndexing, setIsIndexing] = useState(false);

  // BYOK Models & Provider State
  const [providers, setProviders] = useState<ProviderStatusInfo[]>([]);
  const [activeModelCfg, setActiveModelCfg] = useState<ActiveModelConfig | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<string>("groq");
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [baseUrlInput, setBaseUrlInput] = useState("");
  const [customModelInput, setCustomModelInput] = useState("");
  const [customFormatInput, setCustomFormatInput] = useState<"openai" | "anthropic">("openai");
  const [showKey, setShowKey] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string; status_code?: number } | null>(null);

  async function loadBYOKData() {
    try {
      const [pList, aCfg] = await Promise.all([
        fetchModelProviders(),
        fetchActiveModelConfig(),
      ]);
      if (pList && pList.length > 0) setProviders(pList);
      if (aCfg) {
        setActiveModelCfg(aCfg);
        if (aCfg.active_provider) setSelectedProvider(aCfg.active_provider);
      }
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    loadBYOKData();
  }, []);

  async function refreshGithubStatus() {
    try {
      const r = await fetch("/api/github/status");
      const data = await r.json();
      if (data.status === "success" && data.connected) {
        setGhStatus({
          connected: true,
          username: data.user || data.name || data.login,
          source: data.source,
          is_environment_managed: data.is_environment_managed,
          is_vault_managed: data.is_vault_managed,
          rate_limit_remaining: data.rate_limit_remaining,
        });
      } else {
        setGhStatus({ connected: false });
      }
    } catch {
      setGhStatus({ connected: false });
    }
  }

  async function refreshIndexStatus() {
    try {
      const r = await fetch("/api/project/index/status");
      const d = await r.json();
      if (d.status === "success") {
        setIndexStats({
          workspace_path: d.workspace_path,
          project_name: d.project_name,
          total_files: d.total_files || 0,
          total_bytes: d.total_bytes || 0,
          last_indexed_at: d.last_indexed_at || 0,
        });
      }
    } catch {}
  }

  async function triggerWorkspaceScan() {
    setIsIndexing(true);
    try {
      const r = await fetch("/api/project/index", { method: "POST" });
      const d = await r.json();
      if (d.status === "success") {
        toast.success(`Indexed ${d.indexed_count} files (${formatBytes(d.total_bytes)}) in ${d.duration_ms}ms`);
        await refreshIndexStatus();
      } else {
        toast.error(d.message || "Indexing failed");
      }
    } catch {
      toast.error("Failed to trigger workspace index");
    } finally {
      setIsIndexing(false);
    }
  }

  useEffect(() => {
    setGh(loadGithub());
    setIngest(loadIngest());
    refreshGithubStatus();
    refreshIndexStatus();

    fetch("/api/mcp/tools")
      .then((r) => r.json())
      .then((data) => {
        const count = Array.isArray(data.tools) ? data.tools.length : 0;
        setMcpStatus({
          active: count > 0,
          toolsCount: count,
          message: count > 0 ? `${count} tools available` : "Studio MCP idle",
        });
      })
      .catch(() => {
        setMcpStatus({ active: false, toolsCount: 0, message: "MCP backend unreachable" });
      });

    fetch("/api/memory/stats")
      .then((r) => r.json())
      .then((data) => {
        setMemoryStats({ count: data.count || 0, total_bytes: data.total_bytes || 0 });
      })
      .catch(() => {});

    refreshStorageDiag();
  }, []);

  async function onFolder(files: FileList | null) {
    if (!files?.length) return;
    setIsIndexing(true);
    try {
      const ok = Array.from(files).filter((f) =>
        /\.(lua|luau|rbxmx|rbxlx|json|txt|toml|md)$/i.test(f.name),
      );
      let bytes = 0;
      let skipped = 0;
      const lines: string[] = [];

      for (const f of ok.slice(0, 400)) {
        if (f.size > 1024 * 1024) {
          skipped++;
          continue;
        }
        bytes += f.size;
        const path = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
        const depth = path.split("/").length - 1;
        lines.push(`${"  ".repeat(depth)}${path.split("/").pop()} (${formatBytes(f.size)})`);
      }

      const f0 = files[0] as File & { webkitRelativePath?: string };
      const name = (f0.webkitRelativePath || f0.name).split("/")[0] || "project";
      const v = {
        name,
        files: ok.length - skipped,
        bytes,
        map: lines.join("\n").slice(0, 200_000),
        at: Date.now(),
      };
      saveIngest(v);
      setIngest(v);
      toast.success(`Ingested ${ok.length - skipped} files from ${name}`);
      await triggerWorkspaceScan();
    } finally {
      setIsIndexing(false);
    }
  }

  async function handleSaveGithub() {
    saveGithub({ repo: gh.repo });
    if (gh.pat) {
      try {
        const res = await fetch("/api/github/token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: gh.pat }),
        });
        const data = await res.json();
        if (res.ok && data.status === "success") {
          toast.success("GitHub PAT securely stored in machine vault");
          setGh((prev) => ({ ...prev, pat: "" }));
          await refreshGithubStatus();
        } else {
          toast.error(data.message || "Failed to save token to vault");
        }
      } catch {
        toast.error("Failed to connect to backend");
      }
    } else {
      toast.success("Repository configuration saved");
    }
  }

  async function handleDisconnectGithub() {
    try {
      const res = await fetch("/api/github/token", { method: "DELETE" });
      const data = await res.json();
      if (res.ok) {
        if (data.environment_token_present) {
          toast.warning("Vault token cleared, but GITHUB_TOKEN environment variable remains active.");
        } else {
          toast.success("GitHub token cleared from vault.");
        }
        await refreshGithubStatus();
      } else {
        toast.error(data.message || "Failed to disconnect GitHub token");
      }
    } catch {
      toast.error("Failed to disconnect GitHub token");
    }
  }

  async function handleClearMemory() {
    try {
      const res = await fetch("/api/memory/clear", { method: "POST" });
      if (res.ok) {
        setMemoryStats({ count: 0, total_bytes: 0 });
        toast.success("Memory cache cleared");
      }
    } catch {
      toast.error("Failed to clear memory");
    }
  }

  const [storageDiag, setStorageDiag] = useState<StorageDiagnostics | null>(null);

  async function refreshStorageDiag() {
    try {
      const d = await estimateStorage();
      setStorageDiag(d);
    } catch {}
  }

  async function handleExport() {
    try {
      const jsonStr = await exportLocalDataJson();
      const blob = new Blob([jsonStr], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `stroke-conversations-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success("Exported all local conversations");
    } catch (err) {
      toast.error("Export failed: " + (err as Error).message);
    }
  }

  async function handleImport(files: FileList | null) {
    if (!files || files.length === 0) return;
    const file = files[0];
    try {
      const text = await file.text();
      const res = await importLocalDataJson(text);
      if (res.imported > 0) {
        toast.success(`Successfully imported ${res.imported} chat session(s)`);
        window.dispatchEvent(new Event("keyboard:chats"));
        await refreshStorageDiag();
      } else {
        toast.error(`Import failed: ${res.errors.join(", ") || "No valid chats found"}`);
      }
    } catch (err) {
      toast.error("Failed to read file: " + (err as Error).message);
    }
  }

  async function handleClearAllData() {
    if (!window.confirm("Are you sure you want to delete all local conversations and cached data? This action cannot be undone.")) {
      return;
    }
    await idbClearAllChats();
    localStorage.removeItem("keyboard.chats");
    window.dispatchEvent(new Event("keyboard:chats"));
    await refreshStorageDiag();
    toast.success("All local chat records deleted");
  }

  function handleSaveModelPrefs(model: string, reasoningLevel: string) {
    const updated = { model, reasoningLevel };
    setPrefs(updated);
    saveUserPreferences(updated);
    toast.success("Model preferences updated");
  }

  async function handleTestKey() {
    setIsTesting(true);
    setTestResult(null);
    try {
      const res = await testProviderConnection({
        provider: selectedProvider,
        api_key: apiKeyInput.trim() || undefined,
        base_url: selectedProvider === "custom" ? baseUrlInput.trim() : undefined,
        model_id: selectedProvider === "custom" ? customModelInput.trim() : undefined,
        format_type: selectedProvider === "custom" ? customFormatInput : undefined,
      });
      setTestResult(res);
      if (res.success) {
        toast.success(res.message);
      } else {
        toast.error(res.message);
      }
    } catch (e: any) {
      setTestResult({ success: false, message: e.message || "Failed to test connection" });
      toast.error(e.message || "Failed to test connection");
    } finally {
      setIsTesting(false);
    }
  }

  async function handleSaveKey() {
    if (!apiKeyInput.trim()) {
      toast.error("Please enter an API key");
      return;
    }
    setIsSaving(true);
    try {
      await saveProviderCredential({
        provider: selectedProvider,
        api_key: apiKeyInput.trim(),
        base_url: selectedProvider === "custom" ? baseUrlInput.trim() : undefined,
        model_id: selectedProvider === "custom" ? customModelInput.trim() : undefined,
        format_type: selectedProvider === "custom" ? customFormatInput : undefined,
      });
      toast.success(`${selectedProvider.toUpperCase()} key securely stored in OS vault`);
      setApiKeyInput("");
      await loadBYOKData();
    } catch (e: any) {
      toast.error(e.message || "Failed to save API key");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDeleteKey(provider: string) {
    if (!window.confirm(`Are you sure you want to remove the API key for ${provider.toUpperCase()} from your OS credential vault?`)) {
      return;
    }
    try {
      await deleteProviderCredential(provider);
      toast.success(`${provider.toUpperCase()} key removed from vault`);
      await loadBYOKData();
    } catch (e: any) {
      toast.error(e.message || "Failed to remove key");
    }
  }

  async function handleSetActiveModel(provider: string, model: string) {
    try {
      const updated = await saveActiveModelConfig({
        active_provider: provider,
        active_model: model,
      });
      setActiveModelCfg(updated);
      handleSaveModelPrefs(model, updated.reasoning_level || prefs.reasoningLevel);
      toast.success(`Active model set to ${model} (${provider})`);
    } catch (e: any) {
      toast.error(e.message || "Failed to set active model");
    }
  }

  async function handleSetReasoningLevel(level: string) {
    try {
      const updated = await saveActiveModelConfig({ reasoning_level: level });
      setActiveModelCfg(updated);
      handleSaveModelPrefs(prefs.model, level);
      toast.success(`Reasoning effort set to ${level.toUpperCase()}`);
    } catch (e: any) {
      toast.error(e.message || "Failed to update reasoning effort");
    }
  }

  async function handleToggleFallback(allow: boolean) {
    try {
      const updated = await saveActiveModelConfig({ allow_fallback: allow });
      setActiveModelCfg(updated);
      toast.success(allow ? "Fallback enabled" : "Fallback disabled");
    } catch (e: any) {
      toast.error(e.message || "Failed to update fallback preference");
    }
  }

  async function handleSetFallbackProvider(fallbackProvider: string) {
    try {
      const updated = await saveActiveModelConfig({ fallback_provider: fallbackProvider });
      setActiveModelCfg(updated);
      toast.success(`Fallback provider set to ${fallbackProvider}`);
    } catch (e: any) {
      toast.error(e.message || "Failed to set fallback provider");
    }
  }

  const tabs: Array<{ id: TabId; label: string; icon: typeof Sun }> = [
    { id: "appearance", label: "Appearance", icon: Sun },
    { id: "models", label: "Models & Engine", icon: Cpu },
    { id: "workspaces", label: "Workspaces", icon: FolderTree },
    { id: "github", label: "GitHub Vault", icon: Github },
    { id: "mcp", label: "MCP & Studio", icon: Server },
    { id: "memory", label: "Storage & Quota", icon: Database },
  ];

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto px-4 py-8 md:px-10">
        <div className="mx-auto max-w-3xl space-y-6">
          {/* Header */}
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">
              Settings & Integrations
            </h1>
            <p className="mt-1 text-xs text-muted-foreground">
              Configure appearance, local neural models, GitHub vault, MCP tools, and workspace indexing.
            </p>
          </div>

          {/* Minimal Tab Bar */}
          <div className="flex items-center gap-1 overflow-x-auto border-b border-border pb-2">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                    isActive
                      ? "bg-primary text-primary-foreground shadow-2xs"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>

          {/* Tab Content: Appearance */}
          {activeTab === "appearance" && (
            <div className="space-y-4 animate-in fade-in duration-200">
              <section className="rounded-xl border border-border bg-card p-5">
                <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <Sun className="h-4 w-4 text-primary" />
                  Interface Theme
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Select your preferred color appearance. In system mode, Stroke tracks your operating system’s dark/light preferences.
                </p>
                <div className="mt-4">
                  <ThemeSelector />
                </div>
              </section>
            </div>
          )}

          {/* Tab Content: Models & BYOK Engine */}
          {activeTab === "models" && (
            <div className="space-y-6 animate-in fade-in duration-200">
              {/* Active Engine Summary Banner */}
              <section className="rounded-xl border border-border bg-card p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                      <span className="text-xs font-semibold text-foreground uppercase tracking-wide">
                        Active BYOK Engine
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-sm font-medium text-foreground">
                      <span>{activeModelCfg?.active_model || prefs.model}</span>
                      <span className="rounded bg-primary/10 px-2 py-0.5 text-xs text-primary font-semibold uppercase">
                        {activeModelCfg?.active_provider || "groq"}
                      </span>
                      <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground uppercase">
                        Reasoning: {activeModelCfg?.reasoning_level || prefs.reasoningLevel}
                      </span>
                      {activeModelCfg?.allow_fallback && activeModelCfg?.fallback_provider && (
                        <span className="rounded bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-600 dark:text-amber-400">
                          Fallback: {activeModelCfg.fallback_provider}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="text-right">
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/30 px-3 py-1 text-xs font-mono text-muted-foreground">
                      <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
                      Zero Local GGUF / Ollama Dependency
                    </span>
                  </div>
                </div>
              </section>

              {/* Provider Selection Tabs */}
              <section className="rounded-xl border border-border bg-card p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                      <Cpu className="h-4 w-4 text-primary" />
                      AI Provider & Key Management
                    </h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Connect your API keys for supported providers. Keys are encrypted and stored in your OS Keychain / machine vault.
                    </p>
                  </div>
                </div>

                {/* Horizontal Provider Sub-tabs */}
                <div className="mt-4 flex flex-wrap gap-2 border-b border-border pb-3">
                  {[
                    { id: "groq", name: "Groq", badge: "LPU Ultra-Fast" },
                    { id: "gemini", name: "Google Gemini", badge: "2M Multimodal" },
                    { id: "openrouter", name: "OpenRouter", badge: "Universal" },
                    { id: "anthropic", name: "Anthropic", badge: "Claude 3.5" },
                    { id: "openai", name: "OpenAI", badge: "Direct" },
                    { id: "custom", name: "Custom / Proxy", badge: "BYOK URL" },
                  ].map((p) => {
                    const provInfo = providers.find((item) => item.provider === p.id);
                    const isConfigured = provInfo?.configured;
                    const isSelected = selectedProvider === p.id;
                    const isActivePrimary = activeModelCfg?.active_provider === p.id;

                    return (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => {
                          setSelectedProvider(p.id);
                          setTestResult(null);
                          setApiKeyInput("");
                        }}
                        className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-all ${
                          isSelected
                            ? "border-primary bg-primary/10 text-foreground ring-1 ring-primary/30"
                            : "border-border hover:bg-muted text-muted-foreground"
                        }`}
                      >
                        <span
                          className={`h-2 w-2 rounded-full ${
                            isConfigured ? "bg-emerald-500" : "bg-muted-foreground/40"
                          }`}
                        />
                        <span>{p.name}</span>
                        {isActivePrimary && (
                          <span className="rounded bg-primary px-1.5 py-0.2 text-[9px] font-bold text-primary-foreground uppercase">
                            Active
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>

                {/* Active Provider Details & Credential Box */}
                {(() => {
                  const currProv = providers.find((p) => p.provider === selectedProvider);
                  const isConfigured = currProv?.configured;
                  const portalLinks: Record<string, { url: string; label: string; placeholder: string; desc: string }> = {
                    groq: {
                      url: "https://console.groq.com/keys",
                      label: "Get free Groq key at console.groq.com",
                      placeholder: "gsk_...",
                      desc: "Ultra-low latency open-weights inference powered by Groq LPUs. Supports Llama 3.3 70B & tool calling.",
                    },
                    gemini: {
                      url: "https://aistudio.google.com/app/apikey",
                      label: "Get free Gemini key at aistudio.google.com",
                      placeholder: "AIzaSy...",
                      desc: "Google frontier models with massive 2M token context, multimodal attachments, and native tool execution.",
                    },
                    openrouter: {
                      url: "https://openrouter.ai/keys",
                      label: "Get OpenRouter key at openrouter.ai",
                      placeholder: "sk-or-v1-...",
                      desc: "Universal gateway supporting Claude 3.5 Sonnet, DeepSeek R1, Llama 3.3, and 300+ models with one unified key.",
                    },
                    anthropic: {
                      url: "https://console.anthropic.com/settings/keys",
                      label: "Get key at console.anthropic.com",
                      placeholder: "sk-ant-api03-...",
                      desc: "Direct access to Claude 3.5 Sonnet and Haiku with deep reasoning and exceptional coding precision.",
                    },
                    openai: {
                      url: "https://platform.openai.com/api-keys",
                      label: "Get key at platform.openai.com",
                      placeholder: "sk-proj-...",
                      desc: "Direct access to GPT-4o, GPT-4o-mini, o1, and o3-mini reasoning models.",
                    },
                    custom: {
                      url: "",
                      label: "Custom API Endpoint",
                      placeholder: "sk-...",
                      desc: "Configure any OpenAI-compatible or Anthropic-compatible API endpoint (self-hosted, vLLM, Ollama, proxy).",
                    },
                  };

                  const meta = portalLinks[selectedProvider] || portalLinks.groq;

                  return (
                    <div className="mt-4 space-y-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="text-xs text-muted-foreground">{meta.desc}</div>
                        {meta.url && (
                          <a
                            href={meta.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-primary hover:underline font-mono"
                          >
                            <span>{meta.label}</span>
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>

                      {/* Custom Endpoint Specific Inputs */}
                      {selectedProvider === "custom" && (
                        <div className="grid gap-3 sm:grid-cols-2 rounded-lg border border-border bg-muted/10 p-3">
                          <div>
                            <Label className="text-xs font-medium">Base URL</Label>
                            <Input
                              value={baseUrlInput || currProv?.base_url || ""}
                              onChange={(e) => setBaseUrlInput(e.target.value)}
                              placeholder="https://api.openai.com/v1"
                              className="mt-1 font-mono text-xs"
                            />
                            <p className="mt-1 text-[10px] text-muted-foreground">Endpoint serving /chat/completions or /models</p>
                          </div>
                          <div>
                            <Label className="text-xs font-medium">Model ID</Label>
                            <Input
                              value={customModelInput || currProv?.custom_model || ""}
                              onChange={(e) => setCustomModelInput(e.target.value)}
                              placeholder="e.g. meta-llama/Llama-3-70b-chat"
                              className="mt-1 font-mono text-xs"
                            />
                            <p className="mt-1 text-[10px] text-muted-foreground">Default model identifier for this custom host</p>
                          </div>
                          <div className="sm:col-span-2 flex items-center gap-4 pt-1">
                            <span className="text-xs text-muted-foreground">API Format:</span>
                            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                              <input
                                type="radio"
                                name="customFormat"
                                value="openai"
                                checked={customFormatInput === "openai"}
                                onChange={() => setCustomFormatInput("openai")}
                              />
                              <span>OpenAI Compatible</span>
                            </label>
                            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                              <input
                                type="radio"
                                name="customFormat"
                                value="anthropic"
                                checked={customFormatInput === "anthropic"}
                                onChange={() => setCustomFormatInput("anthropic")}
                              />
                              <span>Anthropic Compatible</span>
                            </label>
                          </div>
                        </div>
                      )}

                      {/* API Key Input / Stored Status */}
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <Label className="text-xs font-medium flex items-center gap-1.5">
                            <Key className="h-3.5 w-3.5 text-muted-foreground" />
                            {selectedProvider.toUpperCase()} API Key
                          </Label>
                          {isConfigured && (
                            <span className="flex items-center gap-1 text-[11px] font-mono text-emerald-500">
                              <Lock className="h-3 w-3" />
                              Key stored in OS Keychain ({currProv?.masked_key})
                            </span>
                          )}
                        </div>

                        <div className="flex items-center gap-2">
                          <div className="relative flex-1">
                            <Input
                              type={showKey ? "text" : "password"}
                              value={apiKeyInput}
                              onChange={(e) => setApiKeyInput(e.target.value)}
                              placeholder={isConfigured ? `Key is saved (${currProv?.masked_key}). Enter new key to replace.` : meta.placeholder}
                              className="font-mono text-xs pr-10"
                            />
                            <button
                              type="button"
                              onClick={() => setShowKey(!showKey)}
                              className="absolute right-3 top-2.5 text-muted-foreground hover:text-foreground"
                            >
                              {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                            </button>
                          </div>
                          <Button
                            type="button"
                            variant="secondary"
                            onClick={handleTestKey}
                            disabled={isTesting}
                            size="sm"
                            className="text-xs shrink-0"
                          >
                            {isTesting ? <RefreshCw className="h-3 w-3 animate-spin mr-1.5" /> : null}
                            Test Connection
                          </Button>
                          <Button
                            type="button"
                            onClick={handleSaveKey}
                            disabled={isSaving || !apiKeyInput.trim()}
                            size="sm"
                            className="text-xs shrink-0"
                          >
                            Save Key
                          </Button>
                          {isConfigured && (
                            <Button
                              type="button"
                              variant="destructive"
                              onClick={() => handleDeleteKey(selectedProvider)}
                              size="sm"
                              className="text-xs shrink-0"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          )}
                        </div>

                        {/* Test Connection Results Banner */}
                        {testResult && (
                          <div
                            className={`rounded-lg border p-3 text-xs font-mono flex items-center gap-2 ${
                              testResult.success
                                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                                : "border-destructive/30 bg-destructive/10 text-destructive"
                            }`}
                          >
                            {testResult.success ? (
                              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
                            ) : (
                              <AlertCircle className="h-4 w-4 shrink-0 text-destructive" />
                            )}
                            <span>{testResult.message}</span>
                          </div>
                        )}
                      </div>

                      {/* Models List for Selected Provider */}
                      <div className="pt-4 border-t border-border">
                        <h3 className="text-xs font-semibold text-foreground flex items-center gap-1.5 mb-3">
                          <Sparkles className="h-3.5 w-3.5 text-primary" />
                          Models Available for {selectedProvider.toUpperCase()}
                        </h3>

                        <div className="grid gap-2">
                          {AVAILABLE_MODELS.filter((m) => {
                            if (selectedProvider === "custom") return m.provider === "custom";
                            return m.provider === selectedProvider;
                          }).map((model) => {
                            const isCurrentActive =
                              activeModelCfg?.active_model === model.id ||
                              (!activeModelCfg && prefs.model === model.id);

                            return (
                              <div
                                key={model.id}
                                className={`flex items-center justify-between rounded-lg border p-3 transition-all ${
                                  isCurrentActive
                                    ? "border-primary bg-primary/5 text-foreground ring-1 ring-primary/20"
                                    : "border-border bg-card text-foreground"
                                }`}
                              >
                                <div>
                                  <div className="flex items-center gap-2 font-medium text-xs">
                                    <span>{model.name}</span>
                                    <span className="rounded bg-muted px-1.5 py-0.2 font-mono text-[9px] text-muted-foreground">
                                      {model.id}
                                    </span>
                                    <span className="rounded bg-primary/10 px-1.5 py-0.2 font-mono text-[9px] text-primary">
                                      {model.badge}
                                    </span>
                                  </div>
                                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                                    {model.description}
                                  </div>
                                </div>
                                <div className="flex items-center gap-2">
                                  {isCurrentActive ? (
                                    <span className="inline-flex items-center gap-1 text-xs font-semibold text-primary">
                                      <CheckCircle2 className="h-4 w-4" />
                                      Active
                                    </span>
                                  ) : (
                                    <Button
                                      type="button"
                                      variant="outline"
                                      size="sm"
                                      onClick={() => handleSetActiveModel(selectedProvider, model.id)}
                                      className="text-xs h-7 px-2.5"
                                    >
                                      Set as Default
                                    </Button>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  );
                })()}

                {/* Reasoning Level Selector */}
                <div className="mt-6 pt-5 border-t border-border">
                  <h3 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                    <Brain className="h-3.5 w-3.5 text-indigo-500" />
                    Neural Reasoning Effort & Multi-Turn Verification
                  </h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Scales autonomous thought tokens, verification passes, and agentic tool dispatch turns.
                  </p>
                  <div className="mt-3 grid grid-cols-2 sm:grid-cols-5 gap-2">
                    {REASONING_LEVELS.map((level) => {
                      const isSelected =
                        (activeModelCfg?.reasoning_level || prefs.reasoningLevel) === level.id;
                      return (
                        <button
                          key={level.id}
                          type="button"
                          onClick={() => handleSetReasoningLevel(level.id)}
                          className={`rounded-lg border p-2.5 text-center text-xs transition-all ${
                            isSelected
                              ? "border-primary bg-primary/10 text-foreground font-semibold ring-1 ring-primary/30"
                              : "border-border hover:bg-muted text-muted-foreground"
                          }`}
                        >
                          <div className="font-semibold text-foreground">{level.label}</div>
                          <div className="mt-1 text-[10px] text-muted-foreground line-clamp-2">
                            {level.desc}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Transparent Fallback Settings */}
                <div className="mt-6 pt-5 border-t border-border">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                        <Sliders className="h-3.5 w-3.5 text-amber-500" />
                        Transparent Provider Fallback (Opt-in)
                      </h3>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Automatically route queries to a backup configured provider if the primary provider hits rate limits (429) or times out.
                      </p>
                    </div>
                    <label className="flex items-center gap-2 text-xs cursor-pointer font-medium">
                      <input
                        type="checkbox"
                        checked={activeModelCfg?.allow_fallback ?? false}
                        onChange={(e) => handleToggleFallback(e.target.checked)}
                        className="rounded border-border text-primary focus:ring-primary h-4 w-4"
                      />
                      <span>Enable Fallback</span>
                    </label>
                  </div>

                  {activeModelCfg?.allow_fallback && (
                    <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/20 p-3">
                      <span className="text-xs text-muted-foreground">Backup Provider:</span>
                      <select
                        value={activeModelCfg.fallback_provider || "gemini"}
                        onChange={(e) => handleSetFallbackProvider(e.target.value)}
                        className="rounded border border-border bg-background px-2.5 py-1 text-xs font-mono text-foreground"
                      >
                        <option value="groq">Groq</option>
                        <option value="gemini">Google Gemini</option>
                        <option value="openrouter">OpenRouter</option>
                        <option value="anthropic">Anthropic</option>
                        <option value="openai">OpenAI</option>
                      </select>
                      <span className="text-[11px] text-muted-foreground">
                        Stroke will never switch to an unconfigured provider or hide fallback events from logs.
                      </span>
                    </div>
                  )}
                </div>
              </section>
            </div>
          )}

          {/* Tab Content: Workspaces & Indexing */}
          {activeTab === "workspaces" && (
            <div className="space-y-4 animate-in fade-in duration-200">
              <section className="rounded-xl border border-border bg-card p-5">
                <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <FolderTree className="h-4 w-4 text-primary" />
                  Project Intelligence & Ingestion
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Index your approved workspace (.lua, .luau, .rbxmx, .rbxlx, Rojo/Wally configs). Stroke parses actual code, extracts symbols, excludes secrets, and injects relevant context.
                </p>

                <div className="mt-4 flex flex-wrap items-center gap-2.5">
                  <Button onClick={triggerWorkspaceScan} disabled={isIndexing} size="sm">
                    {isIndexing ? "Indexing Workspace…" : "Scan & Index Workspace"}
                  </Button>
                  <input
                    type="file"
                    multiple
                    onChange={(e) => onFolder(e.target.files)}
                    {...{ webkitdirectory: "", directory: "" }}
                    className="text-xs file:mr-2 file:rounded-md file:border-0 file:bg-secondary file:px-2.5 file:py-1.5 file:text-xs file:text-secondary-foreground cursor-pointer"
                  />
                </div>

                {indexStats.total_files > 0 && (
                  <div className="mt-4 rounded-lg border border-border bg-muted/20 p-3 text-xs font-mono">
                    <div className="text-emerald-500 font-semibold mb-1 flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full bg-emerald-500" />
                      Active Workspace Index
                    </div>
                    <div>Project: {indexStats.project_name || "Workspace"} ({indexStats.workspace_path})</div>
                    <div>Indexed Files: {indexStats.total_files} ({formatBytes(indexStats.total_bytes)})</div>
                    <div>Last Updated: {indexStats.last_indexed_at ? new Date(indexStats.last_indexed_at * 1000).toLocaleTimeString() : "Never"}</div>
                  </div>
                )}

                {ingest && (
                  <pre className="mt-4 max-h-48 overflow-auto rounded-lg border border-border bg-muted/30 p-3 font-mono text-[11px] leading-relaxed">
                    {`${ingest.name} · ${ingest.files} files · ${formatBytes(ingest.bytes)}\n\n${ingest.map}`}
                  </pre>
                )}
              </section>
            </div>
          )}

          {/* Tab Content: GitHub */}
          {activeTab === "github" && (
            <div className="space-y-4 animate-in fade-in duration-200">
              <section className="rounded-xl border border-border bg-card p-5">
                <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <Github className="h-4 w-4 text-primary" />
                  GitHub Integration & Vault
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Tokens are machine-encrypted with AES/Fernet in Stroke's local vault (0600 mode) or read directly from the environment.
                </p>

                <div className="mt-4 grid gap-3 max-w-lg">
                  <div className="space-y-1">
                    <Label htmlFor="pat" className="text-xs">Personal Access Token</Label>
                    <Input
                      id="pat"
                      type="password"
                      value={gh.pat}
                      onChange={(e) => setGh({ ...gh, pat: e.target.value })}
                      placeholder="ghp_…"
                      className="text-xs font-mono"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="repo" className="text-xs">Repository</Label>
                    <Input
                      id="repo"
                      value={gh.repo}
                      onChange={(e) => setGh({ ...gh, repo: e.target.value })}
                      placeholder="owner/repo"
                      className="text-xs font-mono"
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Button onClick={handleSaveGithub} size="sm">Save to Vault</Button>
                    {ghStatus.connected && (
                      <Button variant="outline" size="sm" onClick={handleDisconnectGithub}>
                        Disconnect
                      </Button>
                    )}
                  </div>
                </div>

                <div className="mt-4 rounded-lg border border-border bg-muted/20 p-3 text-xs font-mono">
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-2 w-2 rounded-full ${ghStatus.connected ? "bg-emerald-500" : "bg-muted-foreground"}`}
                    />
                    {ghStatus.connected ? (
                      <span>
                        {ghStatus.is_environment_managed
                          ? `Connected via GITHUB_TOKEN (@${ghStatus.username || "user"})`
                          : `Vault Connected (@${ghStatus.username || "user"})`}
                        {ghStatus.rate_limit_remaining !== undefined && (
                          <span className="ml-1 opacity-75">· Rate: {ghStatus.rate_limit_remaining}</span>
                        )}
                      </span>
                    ) : (
                      "Not linked"
                    )}
                  </div>
                </div>
              </section>
            </div>
          )}

          {/* Tab Content: MCP & Studio */}
          {activeTab === "mcp" && (
            <div className="space-y-4 animate-in fade-in duration-200">
              <section className="rounded-xl border border-border bg-card p-5">
                <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <Server className="h-4 w-4 text-primary" />
                  Roblox Studio MCP Bridge
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Stroke connects to Roblox Studio via the authoritative JSON-RPC Model Context Protocol bridge.
                </p>

                <div className="mt-4 rounded-lg border border-border bg-muted/20 p-3 flex items-center justify-between text-xs font-mono">
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-2 w-2 rounded-full ${mcpStatus.active ? "bg-emerald-500" : "bg-amber-500"}`}
                    />
                    <span>MCP Bridge: {mcpStatus.message}</span>
                  </div>
                  <span className="text-muted-foreground">35 Studio Tools</span>
                </div>
              </section>
            </div>
          )}

          {/* Tab Content: Memory */}
          {activeTab === "memory" && (
            <div className="space-y-4 animate-in fade-in duration-200">
              {/* Local Storage & IndexedDB Diagnostics */}
              <section className="rounded-xl border border-border bg-card p-5">
                <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <HardDrive className="h-4 w-4 text-primary" />
                  Local Browser Persistence (IndexedDB)
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Chats, streaming histories, and durable cursors are stored locally in IndexedDB with transactional guarantees. Quotas vary by browser and disk availability.
                </p>

                {storageDiag && (
                  <div className="mt-4 space-y-3">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-mono text-muted-foreground">
                        Storage Engine: <span className="font-semibold text-foreground">{storageDiag.engine}</span>
                      </span>
                      <span className="font-mono text-muted-foreground">
                        Usage: <span className="font-semibold text-foreground">{storageDiag.usageFormatted}</span> of {storageDiag.quotaFormatted}
                        {storageDiag.percentUsed !== null && (
                          <span className="ml-1 opacity-75">({storageDiag.percentUsed.toFixed(1)}%)</span>
                        )}
                      </span>
                    </div>

                    {storageDiag.percentUsed !== null && (
                      <div className="h-2 w-full overflow-hidden rounded-full bg-muted/40">
                        <div
                          className="h-full bg-primary/75 transition-all duration-300"
                          style={{ width: `${Math.min(100, Math.max(1, storageDiag.percentUsed))}%` }}
                        />
                      </div>
                    )}
                  </div>
                )}

                {/* Data Backup / Portability Actions */}
                <div className="mt-6 border-t border-border/60 pt-4">
                  <h3 className="text-xs font-semibold text-foreground">Data Export, Import & Recovery</h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Export your complete local conversation history to JSON, or import previously saved sessions.
                  </p>

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button variant="outline" size="sm" onClick={handleExport} className="gap-1.5 text-xs">
                      <Download className="h-3.5 w-3.5" />
                      Export All Chats
                    </Button>
                    <label className="inline-flex cursor-pointer items-center justify-center rounded-md border border-input bg-background px-3 py-1.5 text-xs font-medium shadow-sm hover:bg-accent hover:text-accent-foreground">
                      <Upload className="mr-1.5 h-3.5 w-3.5" />
                      Import Chats
                      <input
                        type="file"
                        accept=".json,application/json"
                        className="hidden"
                        onChange={(e) => {
                          handleImport(e.target.files);
                          e.target.value = "";
                        }}
                      />
                    </label>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={handleClearAllData}
                      className="gap-1.5 text-xs ml-auto"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Clear Local Chats
                    </Button>
                  </div>
                </div>
              </section>

              {/* Context Memory & Cache */}
              <section className="rounded-xl border border-border bg-card p-5">
                <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <Database className="h-4 w-4 text-primary" />
                  Backend Context Memory & Cache
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Manage persistent interaction memory and local workspace cache.
                </p>

                <div className="mt-4 space-y-3">
                  <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs font-mono">
                    Stored project records: {memoryStats.count} ({formatBytes(memoryStats.total_bytes)} of 100 MB quota)
                  </div>
                  <Button variant="secondary" size="sm" onClick={handleClearMemory}>
                    Reset Memory Cache
                  </Button>
                </div>
              </section>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
