import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Cpu,
  Brain,
  ShieldCheck,
  CheckCircle2,
  RefreshCw,
  Trash2,
  Key,
  Lock,
  AlertCircle,
  ExternalLink,
  Eye,
  EyeOff,
  Sparkles,
  Search,
  Check,
  PlusCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  fetchModelProviders,
  saveProviderCredential,
  deleteProviderCredential,
  testProviderConnection,
  fetchActiveModelConfig,
  saveActiveModelConfig,
  fetchLiveProviderModels,
  type ProviderStatusInfo,
  type ActiveModelConfig,
  type LiveModelInfo,
  REASONING_LEVELS,
  AVAILABLE_MODELS,
  loadUserPreferences,
  saveUserPreferences,
} from "@/lib/keyboard-store";

export function ModelsManager() {
  const [providers, setProviders] = useState<ProviderStatusInfo[]>([]);
  const [activeModelCfg, setActiveModelCfg] = useState<ActiveModelConfig | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<string>("groq");
  const [apiKeyInput, setApiKeyInput] = useState<string>("");
  const [baseUrlInput, setBaseUrlInput] = useState<string>("");
  const [customModelInput, setCustomModelInput] = useState<string>("");
  const [customFormatInput, setCustomFormatInput] = useState<"openai" | "anthropic">("openai");
  const [showKey, setShowKey] = useState<boolean>(false);
  const [isTesting, setIsTesting] = useState<boolean>(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [liveModels, setLiveModels] = useState<LiveModelInfo[]>([]);
  const [isLoadingLiveModels, setIsLoadingLiveModels] = useState<boolean>(false);
  const [manualModelInput, setManualModelInput] = useState<string>("");
  const [modelFilterQuery, setModelFilterQuery] = useState<string>("");

  useEffect(() => {
    refreshData();
  }, []);

  async function refreshData() {
    try {
      const [provList, activeCfg] = await Promise.all([
        fetchModelProviders(),
        fetchActiveModelConfig(),
      ]);
      setProviders(provList);
      if (activeCfg) {
        setActiveModelCfg(activeCfg);
        if (activeCfg.active_provider) {
          setSelectedProvider(activeCfg.active_provider);
        }
      }
    } catch {
      toast.error("Failed to load provider credentials and configuration");
    }
  }

  // Load live models when selectedProvider changes or when explicitly requested
  useEffect(() => {
    loadModelsForProvider(selectedProvider);
    setTestResult(null);
    setApiKeyInput("");
  }, [selectedProvider]);

  async function loadModelsForProvider(providerId: string) {
    setIsLoadingLiveModels(true);
    try {
      const models = await fetchLiveProviderModels(providerId);
      setLiveModels(models);
    } catch {
      setLiveModels([]);
    } finally {
      setIsLoadingLiveModels(false);
    }
  }

  async function handleSaveKey() {
    if (!apiKeyInput.trim()) {
      toast.error("Please enter a valid API key.");
      return;
    }
    setIsSaving(true);
    try {
      const metaPayload: Record<string, string | undefined> = {};
      if (selectedProvider === "custom") {
        metaPayload.base_url = baseUrlInput.trim();
        metaPayload.model_id = customModelInput.trim();
        metaPayload.format = customFormatInput;
      }
      await saveProviderCredential({
        provider: selectedProvider,
        api_key: apiKeyInput.trim(),
        ...metaPayload,
      });
      toast.success(`Encrypted and securely saved ${selectedProvider.toUpperCase()} key in vault.`);
      setApiKeyInput("");
      setShowKey(false);
      await refreshData();
      await loadModelsForProvider(selectedProvider);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to save key");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDeleteKey(provider: string) {
    if (!confirm(`Are you sure you want to remove the ${provider.toUpperCase()} credentials?`)) {
      return;
    }
    try {
      await deleteProviderCredential(provider);
      toast.success(`Removed ${provider.toUpperCase()} credentials.`);
      setTestResult(null);
      await refreshData();
      await loadModelsForProvider(provider);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to delete key");
    }
  }

  async function handleTestKey() {
    setIsTesting(true);
    setTestResult(null);
    try {
      const payload: {
        provider: string;
        api_key?: string;
        base_url?: string;
        model_id?: string;
        format_type?: string;
      } = { provider: selectedProvider };
      if (apiKeyInput.trim()) payload.api_key = apiKeyInput.trim();
      if (selectedProvider === "custom") {
        if (baseUrlInput.trim()) payload.base_url = baseUrlInput.trim();
        if (customModelInput.trim()) payload.model_id = customModelInput.trim();
        payload.format_type = customFormatInput;
      }
      const res = await testProviderConnection(payload);
      setTestResult(res);
      if (res.success) {
        toast.success(`Connection verified: ${res.message}`);
        await loadModelsForProvider(selectedProvider);
      } else {
        toast.error(`Connection failed: ${res.message}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Connection test failed.";
      setTestResult({ success: false, message: msg });
    } finally {
      setIsTesting(false);
    }
  }

  async function handleSetActiveModel(provider: string, modelId: string) {
    try {
      const updated = await saveActiveModelConfig({
        active_provider: provider,
        active_model: modelId,
      });
      setActiveModelCfg(updated);
      saveUserPreferences({ model: modelId });
      toast.success(`Default model switched to ${modelId} (${provider.toUpperCase()})`);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to set default model");
    }
  }

  async function handleSetManualModel() {
    const trimmed = manualModelInput.trim();
    if (!trimmed) {
      toast.error("Please enter a valid model ID.");
      return;
    }
    await handleSetActiveModel(selectedProvider, trimmed);
    setManualModelInput("");
  }

  async function handleSetReasoningLevel(level: string) {
    try {
      const updated = await saveActiveModelConfig({ reasoning_level: level });
      setActiveModelCfg(updated);
      saveUserPreferences({ reasoningLevel: level });
      toast.success(`Reasoning effort set to ${level.toUpperCase()}`);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to update reasoning effort");
    }
  }

  const currProv = providers.find((p) => p.provider === selectedProvider);
  const isConfigured = currProv?.configured;

  const portalLinks: Record<
    string,
    { url: string; label: string; placeholder: string; desc: string }
  > = {
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

  // Filter models based on search query
  const displayedModels = (
    liveModels.length > 0
      ? liveModels
      : AVAILABLE_MODELS.filter((m) => {
          if (selectedProvider === "custom") return m.provider === "custom";
          return m.provider === selectedProvider;
        }).map((m) => ({
          id: m.id,
          name: m.name,
          provider: m.provider,
          description: m.description,
          context_length: 131072,
        }))
  ).filter((m) => {
    if (!modelFilterQuery.trim()) return true;
    const q = modelFilterQuery.toLowerCase();
    return m.id.toLowerCase().includes(q) || (m.name && m.name.toLowerCase().includes(q));
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Active Engine Summary Banner */}
      <section className="rounded-xl border border-border bg-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-xs font-semibold text-foreground uppercase tracking-wide">
                Active BYOK Neural Engine
              </span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-sm font-medium text-foreground">
              <span>{activeModelCfg?.active_model || "llama-3.3-70b-versatile"}</span>
              <span className="rounded bg-primary/10 px-2 py-0.5 text-xs text-primary font-semibold uppercase">
                {activeModelCfg?.active_provider || "groq"}
              </span>
              <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground uppercase">
                Reasoning: {activeModelCfg?.reasoning_level || "medium"}
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
              OS Keychain & Vault Encrypted
            </span>
          </div>
        </div>
      </section>

      {/* Provider Selection Tabs */}
      <section className="rounded-xl border border-border bg-card p-5">
        <div>
          <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <Cpu className="h-4 w-4 text-primary" />
            AI Providers & API Keys
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Connect your personal API keys. Stroke is completely provider-independent; keys are
            encrypted via machine AES-256 and stored in the OS Keychain.
          </p>
        </div>

        {/* Horizontal Provider Sub-tabs */}
        <div className="mt-4 flex flex-wrap gap-2 border-b border-border pb-3">
          {[
            { id: "groq", name: "Groq", badge: "LPU Ultra-Fast" },
            { id: "gemini", name: "Google Gemini", badge: "2M Multimodal" },
            { id: "openrouter", name: "OpenRouter", badge: "Universal" },
            { id: "anthropic", name: "Anthropic", badge: "Claude 3.5 / 3.7" },
            { id: "openai", name: "OpenAI", badge: "Direct" },
            { id: "custom", name: "Custom / Proxy", badge: "BYOK URL" },
          ].map((p) => {
            const provInfo = providers.find((item) => item.provider === p.id);
            const isProvConfigured = provInfo?.configured;
            const isSelected = selectedProvider === p.id;
            const isActivePrimary = activeModelCfg?.active_provider === p.id;

            return (
              <button
                key={p.id}
                type="button"
                onClick={() => setSelectedProvider(p.id)}
                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-all ${
                  isSelected
                    ? "border-primary bg-primary/10 text-foreground ring-1 ring-primary/30"
                    : "border-border hover:bg-muted text-muted-foreground"
                }`}
              >
                <span
                  className={`h-2 w-2 rounded-full ${
                    isProvConfigured ? "bg-emerald-500" : "bg-muted-foreground/40"
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
                <p className="mt-1 text-[10px] text-muted-foreground">
                  Endpoint serving /chat/completions or /models
                </p>
              </div>
              <div>
                <Label className="text-xs font-medium">Model ID</Label>
                <Input
                  value={customModelInput || currProv?.custom_model || ""}
                  onChange={(e) => setCustomModelInput(e.target.value)}
                  placeholder="e.g. meta-llama/Llama-3-70b-chat"
                  className="mt-1 font-mono text-xs"
                />
                <p className="mt-1 text-[10px] text-muted-foreground">
                  Default model identifier for this custom host
                </p>
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
                  placeholder={
                    isConfigured
                      ? `Key is saved (${currProv?.masked_key}). Enter new key to replace.`
                      : meta.placeholder
                  }
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

          {/* Model Browser & Manual Selection */}
          <div className="pt-4 border-t border-border space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                Available Models for {selectedProvider.toUpperCase()}
              </h3>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => loadModelsForProvider(selectedProvider)}
                  disabled={isLoadingLiveModels}
                  className="text-xs h-7 px-2"
                >
                  <RefreshCw
                    className={`h-3 w-3 mr-1 ${isLoadingLiveModels ? "animate-spin" : ""}`}
                  />
                  Fetch Live Models
                </Button>
              </div>
            </div>

            {/* Manual Model Input Entry */}
            <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/10 p-2.5">
              <div className="flex-1">
                <Input
                  value={manualModelInput}
                  onChange={(e) => setManualModelInput(e.target.value)}
                  placeholder={`Or enter any ${selectedProvider.toUpperCase()} model ID manually (e.g. new model)...`}
                  className="h-8 font-mono text-xs"
                />
              </div>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={handleSetManualModel}
                disabled={!manualModelInput.trim()}
                className="h-8 text-xs shrink-0"
              >
                <PlusCircle className="h-3 w-3 mr-1" />
                Set as Default
              </Button>
            </div>

            {/* Model Search Filter */}
            {displayedModels.length > 5 && (
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  value={modelFilterQuery}
                  onChange={(e) => setModelFilterQuery(e.target.value)}
                  placeholder="Filter available models..."
                  className="h-8 pl-8 font-mono text-xs"
                />
              </div>
            )}

            {/* Models Cards List */}
            <div className="grid gap-2 max-h-[380px] overflow-y-auto pr-1">
              {isLoadingLiveModels ? (
                <div className="py-8 text-center text-xs text-muted-foreground flex items-center justify-center gap-2">
                  <RefreshCw className="h-4 w-4 animate-spin text-primary" />
                  <span>Querying {selectedProvider.toUpperCase()} API for live models…</span>
                </div>
              ) : displayedModels.length === 0 ? (
                <div className="py-6 text-center text-xs text-muted-foreground border border-dashed rounded-lg">
                  No live models returned. Enter a model ID manually above or verify your API key.
                </div>
              ) : (
                displayedModels.map((model) => {
                  const isCurrentActive =
                    activeModelCfg?.active_model === model.id &&
                    activeModelCfg?.active_provider === selectedProvider;

                  return (
                    <div
                      key={model.id}
                      className={`flex items-center justify-between rounded-lg border p-3 transition-all ${
                        isCurrentActive
                          ? "border-primary bg-primary/5 text-foreground ring-1 ring-primary/20"
                          : "border-border bg-card text-foreground hover:border-border/80"
                      }`}
                    >
                      <div className="min-w-0 flex-1 pr-3">
                        <div className="flex flex-wrap items-center gap-2 font-medium text-xs">
                          <span className="truncate">{model.name}</span>
                          <span className="rounded bg-muted px-1.5 py-0.2 font-mono text-[9px] text-muted-foreground">
                            {model.id}
                          </span>
                          {model.context_length && (
                            <span className="rounded bg-primary/10 px-1.5 py-0.2 font-mono text-[9px] text-primary">
                              {Math.round(model.context_length / 1000)}k ctx
                            </span>
                          )}
                        </div>
                        {model.description && (
                          <div className="mt-0.5 text-[11px] text-muted-foreground line-clamp-1">
                            {model.description}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
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
                })
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Reasoning Level Selector */}
      <section className="rounded-xl border border-border bg-card p-5">
        <h3 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
          <Brain className="h-3.5 w-3.5 text-indigo-500" />
          Neural Reasoning Effort & Multi-Turn Verification
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Stroke dynamically adjusts multi-turn verification loops, autonomous planning depth, and
          token budgets based on your chosen effort level.
        </p>

        <div className="mt-4 grid gap-2 sm:grid-cols-5">
          {REASONING_LEVELS.map((lvl) => {
            const isSelected = (activeModelCfg?.reasoning_level || "medium") === lvl.id;
            return (
              <button
                key={lvl.id}
                type="button"
                onClick={() => handleSetReasoningLevel(lvl.id)}
                className={`flex flex-col items-start rounded-lg border p-3 text-left transition-all ${
                  isSelected
                    ? "border-primary bg-primary/10 text-foreground ring-1 ring-primary/30"
                    : "border-border hover:bg-muted text-muted-foreground"
                }`}
              >
                <div className="flex w-full items-center justify-between">
                  <span className="font-semibold text-xs text-foreground">{lvl.name}</span>
                  {isSelected && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
                <span className="mt-1 font-mono text-[10px] text-primary">{lvl.detail}</span>
                <span className="mt-1 text-[10px] text-muted-foreground leading-tight">
                  {lvl.description}
                </span>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
