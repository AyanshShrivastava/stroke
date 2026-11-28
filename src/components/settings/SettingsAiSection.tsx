import React, { useEffect, useState } from 'react';
import {
  CheckCircle2,
  Cpu,
  ExternalLink,
  Eye,
  EyeOff,
  KeyRound,
  Link2,
  Loader2,
  ShieldAlert,
  Tag,
} from 'lucide-react';
import { motion } from 'motion/react';
import type {
  AiProviderConfig,
  MistUser as User,
  ModelVerificationResult,
} from '../../types/mist';
import type { ModelHealthIncident } from '../../utils/aiErrors';
import {
  CUSTOM_GATEWAY_PRESETS,
  detectGatewayFromBaseUrl,
  normalizeProviderConfigToStudio,
  type CustomGatewayId,
} from '../../data/models';
import ModelSelectorDropdown from '../ModelSelectorDropdown';
import { maskApiKey } from '../../utils/projectOps';
import {
  executeProviderTest,
  resolveGatewayBaseUrl,
  useModelCatalog,
} from './settingsAiHelpers';

interface SettingsAiSectionProps {
  user: User | null;
  providerConfig: AiProviderConfig;
  onSaveProvider: (next: AiProviderConfig) => void;
  onIncident: (incident: ModelHealthIncident | null) => void;
}

function GatewayPresetsGrid({
  activeId,
  onSelect,
}: {
  activeId: CustomGatewayId;
  onSelect: (id: CustomGatewayId) => void;
}) {
  return (
    <div>
      <p className="mb-1.5 font-medium text-zinc-700 dark:text-zinc-300">
        Quick-Fill Gateway Preset
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {CUSTOM_GATEWAY_PRESETS.map((gw) => {
          const isSelected = activeId === gw.id;
          return (
            <button
              key={gw.id}
              type="button"
              onClick={() => onSelect(gw.id)}
              className={`min-h-[38px] rounded-xl border px-2.5 py-1.5 text-[11px] font-medium transition-all cursor-pointer ${
                isSelected
                  ? 'border-blue-600 bg-gradient-to-r from-blue-500/15 to-pink-500/15 text-blue-700 dark:border-blue-500/70 dark:text-blue-300'
                  : 'border-zinc-200 bg-white/60 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300 dark:hover:bg-zinc-800'
              }`}
            >
              {gw.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ProviderEndpointInputs({
  providerName,
  baseUrl,
  onChangeProviderName,
  onChangeBaseUrl,
}: {
  providerName: string;
  baseUrl: string;
  onChangeProviderName: (name: string) => void;
  onChangeBaseUrl: (url: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <div>
        <label
          htmlFor="settings-provider-name"
          className="block font-medium text-zinc-700 dark:text-zinc-300"
        >
          <span className="inline-flex items-center gap-1.5">
            <Tag className="h-3.5 w-3.5 text-blue-500" aria-hidden="true" />
            <span>Provider Name</span>
          </span>
        </label>
        <input
          id="settings-provider-name"
          type="text"
          required
          value={providerName}
          onChange={(e) => onChangeProviderName(e.target.value)}
          placeholder="OpenRouter, Groq, My Proxy..."
          className="mt-1.5 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-950 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-white"
        />
      </div>

      <div>
        <label
          htmlFor="settings-custom-url"
          className="block font-medium text-zinc-700 dark:text-zinc-300"
        >
          <span className="inline-flex items-center gap-1.5">
            <Link2 className="h-3.5 w-3.5 text-indigo-500" aria-hidden="true" />
            <span>Base URL</span>
          </span>
        </label>
        <input
          id="settings-custom-url"
          type="url"
          required
          value={baseUrl}
          onChange={(e) => onChangeBaseUrl(e.target.value)}
          placeholder="https://openrouter.ai/api/v1"
          className="mt-1.5 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 font-mono text-xs text-zinc-950 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-white"
        />
      </div>
    </div>
  );
}

function getApiKeyVaultNotice(user: User | null, sessionOnlyKey: boolean): string {
  if (!user?.email) {
    return 'Sign in to Mist to encrypt and sync this API key to your account email across sessions.';
  }
  if (sessionOnlyKey) {
    return `Session-only mode enabled: key stays in RAM and will not be saved to ${user.email}.`;
  }
  return `Encrypted with AES-256-GCM and bound to your Mist account (${user.email}) — zero keys are stored in browser localStorage.`;
}

function ProviderApiKeyCard({
  apiKey,
  showKey,
  sessionOnlyKey,
  activeGateway,
  providerName,
  user,
  onChangeKey,
  onToggleShowKey,
  onChangeSessionOnly,
}: {
  apiKey: string;
  showKey: boolean;
  sessionOnlyKey: boolean;
  activeGateway: (typeof CUSTOM_GATEWAY_PRESETS)[number];
  providerName: string;
  user: User | null;
  onChangeKey: (val: string) => void;
  onToggleShowKey: () => void;
  onChangeSessionOnly: (val: boolean) => void;
}) {
  const masked = maskApiKey(apiKey);
  return (
    <div>
      <label
        htmlFor="settings-byok-key"
        className="block font-medium text-zinc-700 dark:text-zinc-300"
      >
        <span className="inline-flex items-center gap-1.5">
          <KeyRound className="h-3.5 w-3.5 text-sky-500" aria-hidden="true" />
          <span>{providerName.trim() || activeGateway.name} API Key</span>
        </span>
      </label>
      <div className="relative mt-1.5">
        <input
          id="settings-byok-key"
          type={showKey ? 'text' : 'password'}
          required
          value={apiKey}
          onChange={(e) => onChangeKey(e.target.value)}
          placeholder={activeGateway.placeholder}
          className="w-full rounded-xl border border-zinc-200 bg-white pl-3 pr-10 py-2 font-mono text-xs text-zinc-950 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-white"
        />
        <button
          type="button"
          aria-label={showKey ? 'Hide API key' : 'Show API key'}
          onClick={onToggleShowKey}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 cursor-pointer"
        >
          {showKey ? <EyeOff className="h-3.5 w-3.5" aria-hidden="true" /> : <Eye className="h-3.5 w-3.5" aria-hidden="true" />}
        </button>
      </div>
      {masked ? (
        <p className="mt-1.5 text-[11px] text-zinc-600 dark:text-zinc-300">
          Active Key: <span className="font-mono font-semibold text-blue-600 dark:text-blue-400">{masked}</span> — automatically used by Mist generation &amp; <code className="font-mono">/api/app-ai</code>.
        </p>
      ) : null}

      <label className="mt-2 flex items-center gap-2 text-[11px] text-zinc-600 dark:text-zinc-400 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={sessionOnlyKey}
          onChange={(e) => onChangeSessionOnly(e.target.checked)}
          className="h-3.5 w-3.5 rounded border-zinc-300 text-blue-600 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-900"
        />
        <span>Keep API key in memory only (never saved to account vault; clears on close)</span>
      </label>

      <div className="mt-2 rounded-xl border border-zinc-200/80 bg-zinc-50 px-3 py-2 text-[11px] text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-400">
        {getApiKeyVaultNotice(user, sessionOnlyKey)}
      </div>
    </div>
  );
}

function GatewaySetupCard({ gateway }: { gateway: (typeof CUSTOM_GATEWAY_PRESETS)[number] }) {
  if (!gateway.steps) return null;
  return (
    <div className="rounded-xl border border-zinc-200/90 bg-zinc-50/90 p-3.5 space-y-2 dark:border-zinc-800 dark:bg-zinc-900/70">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold text-zinc-900 dark:text-zinc-100">
          How to set up {gateway.name}
        </p>
        {gateway.portalUrl && (
          <a
            href={gateway.portalUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-mono text-[11px] text-blue-600 hover:underline dark:text-blue-400"
          >
            <span>{gateway.portalLabel}</span>
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </a>
        )}
      </div>
      <ol className="list-decimal pl-4 space-y-1 text-[11px] leading-relaxed text-zinc-600 dark:text-zinc-400">
        {gateway.steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
    </div>
  );
}

function ProviderTestResultAlert({
  result,
}: {
  result: { ok: boolean; message: string } | null;
}) {
  if (!result) return null;
  return (
    <div
      role="status"
      className={`flex items-start gap-2 rounded-xl border p-3 ${
        result.ok
          ? 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900/70 dark:bg-emerald-950/40 dark:text-emerald-200'
          : 'border-red-300 bg-red-50 text-red-900 dark:border-red-900/70 dark:bg-red-950/40 dark:text-red-200'
      }`}
    >
      {result.ok ? (
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      ) : (
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      )}
      <p className="text-[11px] leading-relaxed">{result.message}</p>
    </div>
  );
}

export default function SettingsAiSection({
  user,
  providerConfig,
  onSaveProvider,
  onIncident,
}: SettingsAiSectionProps) {
  const normalizedInit = normalizeProviderConfigToStudio(providerConfig);
  const [gatewayId, setGatewayId] = useState<CustomGatewayId>(
    detectGatewayFromBaseUrl(normalizedInit.baseUrl),
  );
  const [providerName, setProviderName] = useState<string>(
    normalizedInit.name || 'OpenRouter',
  );
  const [baseUrl, setBaseUrl] = useState<string>(
    normalizedInit.baseUrl || CUSTOM_GATEWAY_PRESETS[0].baseUrl,
  );
  const [apiKey, setApiKey] = useState<string>(normalizedInit.apiKey || '');
  const [sessionOnlyKey, setSessionOnlyKey] = useState<boolean>(
    Boolean(normalizedInit.sessionOnlyKey),
  );
  const [showKey, setShowKey] = useState(false);
  const [model, setModel] = useState<string>(normalizedInit.model);
  const [savedNotice, setSavedNotice] = useState(false);

  const [isTestingProvider, setIsTestingProvider] = useState(false);
  const [verifiedModel, setVerifiedModel] = useState<ModelVerificationResult | null>(null);
  const [providerTestResult, setProviderTestResult] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);

  const {
    liveModels,
    catalogSource,
    lastRefreshedAt,
    isOutdatedFallback,
    isLoadingCatalog,
    catalogError,
    catalogNote,
    loadCatalog,
    resetCatalog,
  } = useModelCatalog(baseUrl, apiKey, user);

  useEffect(() => {
    const norm = normalizeProviderConfigToStudio(providerConfig);
    setGatewayId(detectGatewayFromBaseUrl(norm.baseUrl));
    setProviderName(norm.name || 'Custom Provider');
    setBaseUrl(norm.baseUrl || '');
    setApiKey(norm.apiKey || '');
    setSessionOnlyKey(Boolean(norm.sessionOnlyKey));
    setModel(norm.model);
    setVerifiedModel(null);
  }, [providerConfig]);

  const activeGateway =
    CUSTOM_GATEWAY_PRESETS.find((g) => g.id === gatewayId) || CUSTOM_GATEWAY_PRESETS[0];
  const activeModelsList = liveModels !== null ? liveModels : activeGateway.models;

  const handleSelectGateway = (nextGwId: CustomGatewayId) => {
    resetCatalog();
    setGatewayId(nextGwId);
    const gw = CUSTOM_GATEWAY_PRESETS.find((g) => g.id === nextGwId)!;
    setProviderName(gw.name);
    setBaseUrl(resolveGatewayBaseUrl(nextGwId, baseUrl));
    setModel(gw.models[0]?.id || '');
    setVerifiedModel(null);
    setProviderTestResult(null);
  };

  const buildProviderDraft = (): AiProviderConfig => ({
    provider: 'custom',
    name: providerName.trim() || activeGateway.name || 'Custom Provider',
    baseUrl: baseUrl.trim(),
    apiKey: apiKey.trim(),
    model: model.trim(),
    sessionOnlyKey,
  });

  const handleApplyProvider = (e: React.FormEvent) => {
    e.preventDefault();
    onSaveProvider(buildProviderDraft());
    setSavedNotice(true);
    window.setTimeout(() => setSavedNotice(false), 1800);
  };

  const handleTestProvider = async () => {
    const draft = buildProviderDraft();
    if (!draft.model) {
      setProviderTestResult({ ok: false, message: 'Select or enter a model ID before testing.' });
      return;
    }
    if (!user) {
      setProviderTestResult({
        ok: false,
        message: 'Sign in to Mist first to test your live BYOK connection.',
      });
      return;
    }

    setIsTestingProvider(true);
    setProviderTestResult(null);
    try {
      const outcome = await executeProviderTest(draft, user);
      onIncident(outcome.incident);
      setVerifiedModel(outcome.verifiedModel);
      setProviderTestResult({ ok: outcome.ok, message: outcome.message });
    } catch (err) {
      setVerifiedModel(null);
      setProviderTestResult({
        ok: false,
        message: err instanceof Error ? err.message : 'Unable to reach provider endpoint.',
      });
    } finally {
      setIsTestingProvider(false);
    }
  };

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.04 }}
      aria-labelledby="settings-ai-heading"
      className="mist-surface-card rounded-2xl border border-zinc-200/90 p-5 sm:p-6 dark:border-zinc-800/90"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl mist-primary-gradient text-white shadow-sm">
            <Cpu className="h-4 w-4" aria-hidden="true" />
          </div>
          <div>
            <h2
              id="settings-ai-heading"
              className="font-display text-base font-semibold text-zinc-950 dark:text-white"
            >
              BYOK AI Endpoint &amp; Models
            </h2>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Mist runs 100% on your own API key, Base URL, and provider name (OpenRouter, Groq, Gemini BYOK, NVIDIA NIM, OpenAI, or any OpenAI-compatible URL).
            </p>
          </div>
        </div>
      </div>

      <form onSubmit={handleApplyProvider} className="mt-5 space-y-4 text-xs">
        <GatewayPresetsGrid activeId={gatewayId} onSelect={handleSelectGateway} />

        <ProviderEndpointInputs
          providerName={providerName}
          baseUrl={baseUrl}
          onChangeProviderName={setProviderName}
          onChangeBaseUrl={(url) => {
            setBaseUrl(url);
            setGatewayId(detectGatewayFromBaseUrl(url));
            setVerifiedModel(null);
          }}
        />

        <ProviderApiKeyCard
          apiKey={apiKey}
          showKey={showKey}
          sessionOnlyKey={sessionOnlyKey}
          activeGateway={activeGateway}
          providerName={providerName}
          user={user}
          onChangeKey={(val) => {
            setApiKey(val);
            setVerifiedModel(null);
          }}
          onToggleShowKey={() => setShowKey((s) => !s)}
          onChangeSessionOnly={setSessionOnlyKey}
        />

        <div>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="font-medium text-zinc-700 dark:text-zinc-300">
              Active Model ({activeModelsList.length} {catalogSource})
            </span>
            <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
              Expand to inspect catalog or enter custom ID
            </span>
          </div>
          <ModelSelectorDropdown
            provider="custom"
            value={model}
            onChange={(nextModel) => {
              setModel(nextModel);
              setVerifiedModel(null);
              setProviderTestResult(null);
            }}
            modelsOverride={activeModelsList}
            gatewayLabel={providerName.trim() || activeGateway.name}
            isLoadingCatalog={isLoadingCatalog}
            isLiveCatalog={catalogSource === 'live'}
            catalogSource={catalogSource}
            lastRefreshedAt={lastRefreshedAt}
            isOutdatedFallback={isOutdatedFallback}
            catalogError={catalogError}
            catalogNote={catalogNote}
            verifiedModel={verifiedModel}
            onRefreshCatalog={() => void loadCatalog(baseUrl, apiKey, true)}
          />
        </div>

        <GatewaySetupCard gateway={activeGateway} />

        <ProviderTestResultAlert result={providerTestResult} />

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 pt-2 border-t border-zinc-200/80 dark:border-zinc-800">
          <button
            type="button"
            disabled={isTestingProvider || !apiKey.trim() || !baseUrl.trim()}
            onClick={() => void handleTestProvider()}
            className="inline-flex w-full sm:w-auto justify-center min-h-[44px] sm:min-h-[40px] items-center gap-1.5 rounded-xl border border-zinc-200 bg-white px-3.5 py-2 font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
          >
            {isTestingProvider && (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            )}
            <span>{isTestingProvider ? 'Testing...' : 'Test Connection'}</span>
          </button>

          <div className="flex flex-col-reverse sm:flex-row sm:items-center gap-2.5">
            {savedNotice && (
              <span className="text-center sm:text-left text-xs font-medium text-emerald-600 dark:text-emerald-400">
                Saved
              </span>
            )}
            <button
              type="submit"
              className="w-full sm:w-auto min-h-[44px] sm:min-h-[40px] rounded-xl mist-primary-gradient px-4 py-2 font-medium text-white shadow-sm transition-all cursor-pointer"
            >
              Save Provider Settings
            </button>
          </div>
        </div>
      </form>
    </motion.section>
  );
}