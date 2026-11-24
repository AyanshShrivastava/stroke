import React, { useRef, useState } from 'react';
import {
  CheckCircle2,
  ExternalLink,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Search,
  ShieldAlert,
} from 'lucide-react';
import { motion } from 'motion/react';
import type { MistUser as User, StudioSettings, WebSearchConfig, WebSearchMode, WebSearchProviderId } from '../../types/mist';
import { normalizeWebSearchConfig, WEB_SEARCH_PRESETS } from '../../data/webSearch';

interface SettingsWebSearchSectionProps {
  user: User | null;
  webSearchConfig: WebSearchConfig;
  studioSettings: StudioSettings;
  onSaveWebSearch: (next: WebSearchConfig) => void;
  onUpdateSettings: (partial: Partial<StudioSettings>) => void;
}

function validateSearchDraft(
  draft: WebSearchConfig,
  requiresApiKey: boolean,
  user: User | null
): string | null {
  if (requiresApiKey && !draft.apiKey?.trim()) {
    return 'Enter your Web Search API key before testing.';
  }
  if (!draft.baseUrl?.trim()) {
    return 'Enter a valid https:// search endpoint URL.';
  }
  if (!user) {
    return 'Sign in with Google first to test your live Web Search connection.';
  }
  return null;
}

async function executeWebSearchTest(
  draft: WebSearchConfig,
  user: User,
  signal: AbortSignal
): Promise<{ ok: boolean; message: string }> {
  const idToken = await user.getIdToken();
  const resp = await fetch('/api/search/test', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${idToken}`,
    },
    signal,
    body: JSON.stringify({ searchConfig: draft }),
  });
  const data = (await resp.json().catch(() => ({}))) as {
    ok?: boolean;
    resultCount?: number;
    error?: string;
  };
  if (!resp.ok || !data.ok) {
    return {
      ok: false,
      message: data.error || `Search test failed (${resp.status}).`,
    };
  }
  const count = data.resultCount ?? 0;
  return {
    ok: true,
    message: `${draft.name} verified (${count} live source${count === 1 ? '' : 's'} retrieved).`,
  };
}

function WebSearchPresetsGrid({
  activeProvider,
  onSelect,
}: {
  activeProvider: WebSearchProviderId;
  onSelect: (id: WebSearchProviderId) => void;
}) {
  const activePreset = WEB_SEARCH_PRESETS.find((p) => p.id === activeProvider) || WEB_SEARCH_PRESETS[0];
  return (
    <div>
      <p className="mb-1.5 font-medium text-zinc-700 dark:text-zinc-300">
        Search Provider Preset
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {WEB_SEARCH_PRESETS.map((preset) => {
          const isSelected = activeProvider === preset.id;
          return (
            <button
              key={preset.id}
              type="button"
              onClick={() => onSelect(preset.id)}
              className={`min-h-[38px] rounded-xl border px-2.5 py-1.5 text-[11px] font-medium transition-all cursor-pointer ${
                isSelected
                  ? 'border-blue-600 bg-gradient-to-r from-blue-500/15 to-fuchsia-500/15 text-blue-700 dark:border-blue-500/70 dark:text-blue-300'
                  : 'border-zinc-200 bg-white/60 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300 dark:hover:bg-zinc-800'
              }`}
            >
              {preset.name}
            </button>
          );
        })}
      </div>
      <p className="mt-1.5 text-[11px] text-zinc-500 dark:text-zinc-400">
        {activePreset.description}
      </p>
    </div>
  );
}

function WebSearchApiKeyField({
  searchName,
  activePreset,
  searchApiKey,
  showSearchKey,
  searchSessionOnlyKey,
  onChangeKey,
  onToggleShowKey,
  onChangeSessionOnly,
}: {
  searchName: string;
  activePreset: (typeof WEB_SEARCH_PRESETS)[number];
  searchApiKey: string;
  showSearchKey: boolean;
  searchSessionOnlyKey: boolean;
  onChangeKey: (val: string) => void;
  onToggleShowKey: () => void;
  onChangeSessionOnly: (val: boolean) => void;
}) {
  if (activePreset.requiresApiKey === false) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-emerald-200/90 bg-emerald-50/70 px-3 py-2.5 text-[11px] text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
        <span>No API key required — DuckDuckGo queries run directly from Mist&apos;s backend.</span>
      </div>
    );
  }

  return (
    <div>
      <label
        htmlFor="settings-search-key"
        className="block font-medium text-zinc-700 dark:text-zinc-300"
      >
        <span className="inline-flex items-center gap-1.5">
          <KeyRound className="h-3.5 w-3.5 text-sky-500" aria-hidden="true" />
          <span>{searchName.trim() || activePreset.name} API Key</span>
        </span>
      </label>
      <div className="relative mt-1.5">
        <input
          id="settings-search-key"
          type={showSearchKey ? 'text' : 'password'}
          value={searchApiKey}
          onChange={(e) => onChangeKey(e.target.value)}
          placeholder={activePreset.placeholder}
          className="w-full rounded-xl border border-zinc-200 bg-white pl-3 pr-10 py-2 font-mono text-xs text-zinc-950 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-white"
        />
        <button
          type="button"
          aria-label={showSearchKey ? 'Hide search API key' : 'Show search API key'}
          onClick={onToggleShowKey}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 cursor-pointer"
        >
          {showSearchKey ? (
            <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <Eye className="h-3.5 w-3.5" aria-hidden="true" />
          )}
        </button>
      </div>
      <label className="mt-2 flex items-center gap-2 text-[11px] text-zinc-600 dark:text-zinc-400 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={searchSessionOnlyKey}
          onChange={(e) => onChangeSessionOnly(e.target.checked)}
          className="h-3.5 w-3.5 rounded border-zinc-300 text-blue-600 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-900"
        />
        <span>Keep search API key in memory only (never synced to account vault or localStorage)</span>
      </label>
    </div>
  );
}

function WebSearchStepsCard({ preset }: { preset: (typeof WEB_SEARCH_PRESETS)[number] }) {
  if (!preset.steps) return null;
  return (
    <div className="rounded-xl border border-zinc-200/90 bg-zinc-50/90 p-3.5 space-y-2 dark:border-zinc-800 dark:bg-zinc-900/70">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold text-zinc-900 dark:text-zinc-100">
          How to connect {preset.name}
        </p>
        {preset.portalUrl ? (
          <a
            href={preset.portalUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-mono text-[11px] text-blue-600 hover:underline dark:text-blue-400"
          >
            <span>{preset.portalLabel}</span>
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </a>
        ) : null}
      </div>
      <ol className="list-decimal pl-4 space-y-1 text-[11px] leading-relaxed text-zinc-600 dark:text-zinc-400">
        {preset.steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
    </div>
  );
}

function WebSearchTestStatusAlert({ result }: { result: { ok: boolean; message: string } | null }) {
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

export default function SettingsWebSearchSection({
  user,
  webSearchConfig,
  studioSettings,
  onSaveWebSearch,
  onUpdateSettings,
}: SettingsWebSearchSectionProps) {
  const normalizedSearchInit = normalizeWebSearchConfig(webSearchConfig);
  const [searchProvider, setSearchProvider] = useState<WebSearchProviderId>(normalizedSearchInit.provider);
  const [searchName, setSearchName] = useState<string>(normalizedSearchInit.name || WEB_SEARCH_PRESETS[0].name);
  const [searchBaseUrl, setSearchBaseUrl] = useState<string>(normalizedSearchInit.baseUrl || WEB_SEARCH_PRESETS[0].baseUrl);
  const [searchApiKey, setSearchApiKey] = useState<string>(normalizedSearchInit.apiKey || '');
  const [searchSessionOnlyKey, setSearchSessionOnlyKey] = useState<boolean>(Boolean(normalizedSearchInit.sessionOnlyKey));
  const [searchMaxResults, setSearchMaxResults] = useState<number>(normalizedSearchInit.maxResults || 5);
  const [showSearchKey, setShowSearchKey] = useState(false);
  const [searchSavedNotice, setSearchSavedNotice] = useState(false);
  const [isTestingSearch, setIsTestingSearch] = useState(false);
  const [searchTestResult, setSearchTestResult] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);

  const searchTestAbortRef = useRef<AbortController | null>(null);

  const activeSearchPreset =
    WEB_SEARCH_PRESETS.find((p) => p.id === searchProvider) || WEB_SEARCH_PRESETS[0];

  const handleSelectSearchPreset = (nextProviderId: WebSearchProviderId) => {
    const preset = WEB_SEARCH_PRESETS.find((p) => p.id === nextProviderId) || WEB_SEARCH_PRESETS[0];
    setSearchProvider(nextProviderId);
    setSearchName(preset.name);
    if (preset.baseUrl) {
      setSearchBaseUrl(preset.baseUrl);
    } else if (
      nextProviderId === 'custom_json' &&
      WEB_SEARCH_PRESETS.some((p) => p.baseUrl === searchBaseUrl)
    ) {
      setSearchBaseUrl('');
    }
    setSearchTestResult(null);
  };

  const buildSearchDraft = (): WebSearchConfig =>
    normalizeWebSearchConfig({
      provider: searchProvider,
      name: searchName,
      baseUrl: searchBaseUrl,
      apiKey: searchApiKey,
      sessionOnlyKey: searchSessionOnlyKey,
      maxResults: searchMaxResults,
    });

  const handleApplyWebSearch = (e: React.FormEvent) => {
    e.preventDefault();
    onSaveWebSearch(buildSearchDraft());
    setSearchSavedNotice(true);
    window.setTimeout(() => setSearchSavedNotice(false), 1800);
  };

  const handleTestWebSearch = async () => {
    const draft = buildSearchDraft();
    const validationError = validateSearchDraft(
      draft,
      activeSearchPreset.requiresApiKey !== false,
      user
    );
    if (validationError) {
      setSearchTestResult({ ok: false, message: validationError });
      return;
    }
    if (!user) return;

    searchTestAbortRef.current?.abort();
    const controller = new AbortController();
    searchTestAbortRef.current = controller;
    setIsTestingSearch(true);
    setSearchTestResult(null);

    try {
      const result = await executeWebSearchTest(draft, user, controller.signal);
      setSearchTestResult(result);
    } catch (err) {
      if (!controller.signal.aborted) {
        setSearchTestResult({
          ok: false,
          message: err instanceof Error ? err.message : 'Unable to reach Web Search service.',
        });
      }
    } finally {
      setIsTestingSearch(false);
    }
  };

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.06 }}
      aria-labelledby="settings-web-search-heading"
      className="mist-surface-card rounded-2xl border border-zinc-200/90 p-5 sm:p-6 dark:border-zinc-800/90"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl mist-primary-gradient text-white shadow-sm">
            <Search className="h-4 w-4" aria-hidden="true" />
          </div>
          <div>
            <h2
              id="settings-web-search-heading"
              className="font-display text-base font-semibold text-zinc-950 dark:text-white"
            >
              Web Search Settings
            </h2>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              DuckDuckGo (built-in &amp; free), Tavily, Exa, Brave Search, or your own search endpoint.
            </p>
          </div>
        </div>
      </div>

      <form onSubmit={handleApplyWebSearch} className="mt-5 space-y-4 text-xs">
        <WebSearchPresetsGrid
          activeProvider={searchProvider}
          onSelect={handleSelectSearchPreset}
        />

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label
              htmlFor="settings-search-name"
              className="block font-medium text-zinc-700 dark:text-zinc-300"
            >
              Search Label
            </label>
            <input
              id="settings-search-name"
              type="text"
              value={searchName}
              onChange={(e) => setSearchName(e.target.value)}
              placeholder="DuckDuckGo (Free · No Key)"
              className="mt-1.5 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-950 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-white"
            />
          </div>
          <div>
            <label
              htmlFor="settings-search-url"
              className="block font-medium text-zinc-700 dark:text-zinc-300"
            >
              Search Endpoint URL
            </label>
            <input
              id="settings-search-url"
              type="url"
              required
              value={searchBaseUrl}
              onChange={(e) => {
                setSearchBaseUrl(e.target.value);
                setSearchTestResult(null);
              }}
              placeholder="https://html.duckduckgo.com/html/"
              className="mt-1.5 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 font-mono text-xs text-zinc-950 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-white"
            />
          </div>
        </div>

        <WebSearchApiKeyField
          searchName={searchName}
          activePreset={activeSearchPreset}
          searchApiKey={searchApiKey}
          showSearchKey={showSearchKey}
          searchSessionOnlyKey={searchSessionOnlyKey}
          onChangeKey={(val) => {
            setSearchApiKey(val);
            setSearchTestResult(null);
          }}
          onToggleShowKey={() => setShowSearchKey((v) => !v)}
          onChangeSessionOnly={setSearchSessionOnlyKey}
        />

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label
              htmlFor="settings-search-default-mode"
              className="block font-medium text-zinc-700 dark:text-zinc-300"
            >
              Default Search Behavior
            </label>
            <select
              id="settings-search-default-mode"
              value={studioSettings.webSearchMode || 'auto'}
              onChange={(e) =>
                onUpdateSettings({
                  webSearchMode: e.target.value as WebSearchMode,
                })
              }
              className="mt-1.5 w-full min-h-[38px] rounded-xl border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-950 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-white"
            >
              <option value="auto">Auto (when current facts are needed)</option>
              <option value="on">Always On</option>
              <option value="off">Off</option>
            </select>
          </div>

          <div>
            <label
              htmlFor="settings-search-max-results"
              className="block font-medium text-zinc-700 dark:text-zinc-300"
            >
              Max Sources per Query
            </label>
            <select
              id="settings-search-max-results"
              value={searchMaxResults}
              onChange={(e) => setSearchMaxResults(Number(e.target.value))}
              className="mt-1.5 w-full min-h-[38px] rounded-xl border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-950 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-white"
            >
              <option value={3}>3 sources (fast &amp; compact)</option>
              <option value={5}>5 sources (balanced)</option>
              <option value={8}>8 sources (deep research)</option>
            </select>
          </div>
        </div>

        <WebSearchStepsCard preset={activeSearchPreset} />

        <WebSearchTestStatusAlert result={searchTestResult} />

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 pt-2 border-t border-zinc-200/80 dark:border-zinc-800">
          <button
            type="button"
            disabled={
              isTestingSearch ||
              !searchBaseUrl.trim() ||
              (activeSearchPreset.requiresApiKey !== false && !searchApiKey.trim())
            }
            onClick={() => void handleTestWebSearch()}
            className="inline-flex w-full sm:w-auto justify-center min-h-[44px] sm:min-h-[40px] items-center gap-1.5 rounded-xl border border-zinc-200 bg-white px-3.5 py-2 font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
          >
            {isTestingSearch && (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            )}
            <span>{isTestingSearch ? 'Testing Search...' : 'Test Search Connection'}</span>
          </button>

          <div className="flex flex-col-reverse sm:flex-row sm:items-center gap-2.5">
            {searchSavedNotice && (
              <span className="text-center sm:text-left text-xs font-medium text-emerald-600 dark:text-emerald-400">
                Saved
              </span>
            )}
            <button
              type="submit"
              className="w-full sm:w-auto min-h-[44px] sm:min-h-[40px] rounded-xl mist-primary-gradient px-4 py-2 font-medium text-white shadow-sm transition-all cursor-pointer"
            >
              Save Web Search Settings
            </button>
          </div>
        </div>
      </form>
    </motion.section>
  );
}