import React, { useMemo, useState } from 'react';
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  Loader2,
  RefreshCw,
  Search,
  ShieldAlert,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import type {
  AiProviderId,
  CatalogSource,
  ModelBilling,
  ModelLifecycleStatus,
  ModelVerificationResult,
} from '../types/mist';
import { PROVIDER_CATALOG, type ModelCatalogItem } from '../data/models';

interface ModelSelectorDropdownProps {
  provider: AiProviderId;
  value: string;
  onChange: (modelId: string) => void;
  modelsOverride?: ModelCatalogItem[];
  gatewayLabel?: string;
  allowCustomInput?: boolean;
  compact?: boolean;
  isLoadingCatalog?: boolean;
  isLiveCatalog?: boolean;
  catalogSource?: CatalogSource;
  lastRefreshedAt?: string | null;
  isOutdatedFallback?: boolean;
  catalogError?: string | null;
  catalogNote?: string | null;
  verifiedModel?: ModelVerificationResult | null;
  onRefreshCatalog?: () => void;
}

function LifecycleBadge({ status }: { status?: ModelLifecycleStatus }) {
  if (!status || status === 'active') return null;
  const label =
    status === 'preview'
      ? 'Preview'
      : status === 'deprecated'
        ? 'Deprecated'
        : status === 'retired'
          ? 'Retired'
          : 'Unverified';
  const classes =
    status === 'preview'
      ? 'bg-indigo-500/10 text-indigo-700 dark:text-indigo-300 border border-indigo-500/25'
      : status === 'deprecated' || status === 'retired'
        ? 'bg-red-500/10 text-red-700 dark:text-red-300 border border-red-500/25'
        : 'bg-zinc-200/80 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 border border-zinc-300 dark:border-zinc-700';

  return (
    <span
      className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium tracking-tight whitespace-nowrap shrink-0 ${classes}`}
    >
      {label}
    </span>
  );
}

function formatCtxWindow(ctx?: number): string | null {
  if (!ctx || !Number.isFinite(ctx)) return null;
  if (ctx >= 1_000_000) return `${(ctx / 1_000_000).toFixed(1).replace(/\.0$/, '')}M ctx`;
  return `${Math.round(ctx / 1000)}k ctx`;
}

function formatRefreshedTime(iso?: string | null): string | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return null;
  try {
    return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return null;
  }
}

export default function ModelSelectorDropdown({
  provider,
  value,
  onChange,
  modelsOverride,
  gatewayLabel,
  allowCustomInput = true,
  compact = false,
  isLoadingCatalog = false,
  isLiveCatalog = false,
  catalogSource,
  lastRefreshedAt,
  isOutdatedFallback = false,
  catalogError,
  catalogNote,
  verifiedModel,
  onRefreshCatalog,
}: ModelSelectorDropdownProps) {
  const [expanded, setExpanded] = useState(false);
  const [filterQuery, setFilterQuery] = useState('');

  const catalog = PROVIDER_CATALOG[provider];
  const modelsList = modelsOverride !== undefined ? modelsOverride : catalog.models;
  const displayGroupName = gatewayLabel || catalog.name;
  const activeEntry = modelsList.find((m) => m.id === value);

  const effectiveSource: CatalogSource =
    catalogSource || (isLiveCatalog ? 'live' : 'preset');
  const refreshedTimeLabel = formatRefreshedTime(lastRefreshedAt);
  const isValueVerified = Boolean(
    verifiedModel?.verified && verifiedModel.model === value.trim(),
  );

  const filteredModels = useMemo(() => {
    const q = filterQuery.trim().toLowerCase();
    return modelsList.filter((m) => {
      if (!q) return true;
      return (
        m.id.toLowerCase().includes(q) ||
        m.label.toLowerCase().includes(q) ||
        m.summary.toLowerCase().includes(q) ||
        m.tier.toLowerCase().includes(q)
      );
    });
  }, [modelsList, filterQuery]);

  const sourceLabel =
    effectiveSource === 'live'
      ? 'Live catalog'
      : effectiveSource === 'cached'
        ? 'Cached catalog'
        : isOutdatedFallback
          ? 'Preset fallback (may be outdated)'
          : 'Preset catalog';

  return (
    <div className="space-y-2">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((prev) => !prev)}
        className={`flex w-full items-center justify-between gap-3 rounded-xl border border-zinc-200 bg-white text-left transition-all hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-700 cursor-pointer ${
          compact ? 'px-3 py-2 text-xs' : 'px-3.5 py-2.5 text-xs'
        }`}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-semibold text-zinc-950 dark:text-white truncate">
              {activeEntry ? activeEntry.label : value || `Select or enter a ${displayGroupName} model`}
            </span>
            {activeEntry ? (
              <>
                <LifecycleBadge status={activeEntry.status} />
                <span className="text-[10px] font-medium text-blue-600 dark:text-blue-400 whitespace-nowrap shrink-0">
                  {activeEntry.tier}
                </span>
              </>
            ) : value ? (
              isValueVerified ? (
                <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/12 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700 dark:text-emerald-300">
                  <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                  <span>Verified</span>
                </span>
              ) : (
                <LifecycleBadge status="unverified" />
              )
            ) : null}
          </div>
          <p className="mt-0.5 truncate font-mono text-[11px] text-zinc-500 dark:text-zinc-400">
            {value || 'No model selected yet'}
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <span className="hidden sm:inline text-[11px] font-medium text-zinc-500 dark:text-zinc-400 tabular-nums">
            {isLoadingCatalog
              ? 'Loading...'
              : `${modelsList.length} ${effectiveSource}`}
          </span>
          <motion.span
            animate={{ rotate: expanded ? 180 : 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
          >
            <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
          </motion.span>
        </div>
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden rounded-xl border border-zinc-200 bg-zinc-50/90 dark:border-zinc-800 dark:bg-zinc-900/80"
          >
            <div className="p-2.5 space-y-2">
              <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                <div className="relative flex-1">
                  <Search
                    className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400"
                    aria-hidden="true"
                  />
                  <input
                    type="search"
                    value={filterQuery}
                    onChange={(e) => setFilterQuery(e.target.value)}
                    placeholder={`Search ${modelsList.length} ${displayGroupName} models...`}
                    aria-label={`Filter ${displayGroupName} models`}
                    className="w-full min-h-[34px] rounded-lg border border-zinc-200 bg-white pl-8 pr-3 py-1.5 text-xs text-zinc-950 placeholder:text-zinc-400 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100"
                  />
                </div>

                <div className="flex items-center gap-1.5 ml-auto">
                  {onRefreshCatalog && (
                    <button
                      type="button"
                      onClick={onRefreshCatalog}
                      disabled={isLoadingCatalog}
                      aria-label="Refresh live model catalog"
                      title="Refresh live model catalog"
                      className="inline-flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-lg border border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-100 hover:text-zinc-950 disabled:opacity-50 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white transition-colors cursor-pointer"
                    >
                      <RefreshCw
                        className={`h-3.5 w-3.5 ${isLoadingCatalog ? 'animate-spin' : ''}`}
                        aria-hidden="true"
                      />
                    </button>
                  )}
                </div>
              </div>

              {/* Catalog Source & Last Refreshed Metadata */}
              <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-[11px]">
                <span
                  className={`font-medium ${
                    isOutdatedFallback
                      ? 'text-amber-700 dark:text-amber-300'
                      : effectiveSource === 'live'
                        ? 'text-emerald-700 dark:text-emerald-400'
                        : 'text-zinc-500 dark:text-zinc-400'
                  }`}
                >
                  {sourceLabel}
                  {refreshedTimeLabel ? ` · Updated ${refreshedTimeLabel}` : ''}
                </span>
                {catalogNote && (
                  <span className="text-zinc-500 dark:text-zinc-400 truncate max-w-full">
                    {catalogNote}
                  </span>
                )}
              </div>

              {isOutdatedFallback && !catalogError && (
                <div
                  role="status"
                  className="flex items-start gap-2 rounded-lg border border-amber-300/80 bg-amber-50 px-2.5 py-2 text-[11px] text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-200"
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
                  <span>
                    Showing fallback presets because the live provider catalog could not be loaded. Models may be outdated.
                  </span>
                </div>
              )}

              {catalogError && (
                <div
                  role="alert"
                  className="flex items-center justify-between gap-2 rounded-lg border border-red-300/80 bg-red-50 px-2.5 py-2 text-[11px] text-red-900 dark:border-red-800/70 dark:bg-red-950/40 dark:text-red-200"
                >
                  <span className="inline-flex items-start gap-1.5 min-w-0">
                    <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    <span className="break-words">{catalogError}</span>
                  </span>
                  {onRefreshCatalog && (
                    <button
                      type="button"
                      onClick={onRefreshCatalog}
                      disabled={isLoadingCatalog}
                      className="shrink-0 rounded-md border border-red-400/60 bg-white px-2 py-1 text-[10px] font-semibold text-red-700 hover:bg-red-50 dark:bg-zinc-900 dark:text-red-200 cursor-pointer"
                    >
                      Retry
                    </button>
                  )}
                </div>
              )}

              <div
                role="listbox"
                aria-label={`${displayGroupName} models`}
                className="max-h-64 overflow-y-auto divide-y divide-zinc-200/70 rounded-lg border border-zinc-200 bg-white dark:divide-zinc-800/80 dark:border-zinc-800 dark:bg-zinc-950 mist-scrollbar"
              >
                {isLoadingCatalog && modelsList.length === 0 ? (
                  <div className="flex items-center justify-center gap-2 px-3 py-6 text-[11px] text-zinc-500">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" aria-hidden="true" />
                    <span>Fetching live {displayGroupName} model catalog...</span>
                  </div>
                ) : filteredModels.length === 0 ? (
                  <div className="px-3 py-5 text-center space-y-2">
                    <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
                      {modelsList.length === 0
                        ? `No live models loaded for ${displayGroupName}. Add an API key to query the provider, or enter a custom model ID below.`
                        : 'No matching model found in this view — clear your filter or enter any model ID below.'}
                    </p>
                    {onRefreshCatalog && modelsList.length === 0 && (
                      <button
                        type="button"
                        onClick={onRefreshCatalog}
                        disabled={isLoadingCatalog}
                        className="inline-flex items-center gap-1 rounded-md border border-zinc-300 bg-zinc-50 px-2.5 py-1 text-[11px] font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 cursor-pointer"
                      >
                        <RefreshCw className="h-3 w-3" aria-hidden="true" />
                        <span>Fetch Live Catalog</span>
                      </button>
                    )}
                  </div>
                ) : (
                  filteredModels.map((item) => {
                    const selected = value === item.id;
                    const ctxLabel = formatCtxWindow(item.contextLength);
                    const caps = item.capabilities;
                    const capTags = [
                      caps?.jsonOutput === true ? 'JSON' : null,
                      caps?.streaming === true ? 'Stream' : null,
                      caps?.imageInput === true ? 'Vision' : null,
                      caps?.toolCalling === true ? 'Tools' : null,
                    ].filter(Boolean) as string[];

                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="option"
                        aria-selected={selected}
                        onClick={() => {
                          onChange(item.id);
                          setExpanded(false);
                        }}
                        className={`flex w-full items-start justify-between gap-3 px-3 py-2.5 text-left transition-colors cursor-pointer ${
                          selected
                            ? 'bg-blue-50/90 dark:bg-blue-500/10'
                            : 'hover:bg-zinc-50 dark:hover:bg-zinc-900'
                        } ${item.status === 'retired' || item.status === 'deprecated' ? 'opacity-70' : ''}`}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span
                              className={`text-xs font-medium ${
                                selected
                                  ? 'text-blue-700 dark:text-blue-300'
                                  : 'text-zinc-900 dark:text-zinc-100'
                              }`}
                            >
                              {item.label}
                            </span>
                            <LifecycleBadge status={item.status} />
                            <span className="text-[10px] font-medium text-zinc-500 dark:text-zinc-400">
                              {item.tier}
                            </span>
                            {ctxLabel && (
                              <span className="text-[10px] font-mono text-zinc-400 dark:text-zinc-500 tabular-nums">
                                {ctxLabel}
                              </span>
                            )}
                          </div>
                          <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400 line-clamp-1">
                            {item.summary}
                          </p>
                          <div className="mt-0.5 flex flex-wrap items-center gap-2">
                            <span className="font-mono text-[10px] text-zinc-400 dark:text-zinc-500 truncate">
                              {item.id}
                            </span>
                            {capTags.length > 0 && (
                              <span className="text-[10px] text-zinc-500 dark:text-zinc-400">
                                {capTags.join(' · ')}
                              </span>
                            )}
                          </div>
                        </div>

                        {selected && (
                          <Check
                            className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-600 dark:text-blue-400"
                            aria-hidden="true"
                          />
                        )}
                      </button>
                    );
                  })
                )}
              </div>

              {allowCustomInput && (
                <div className="pt-1">
                  <label
                    htmlFor={`custom-model-input-${provider}`}
                    className="block text-[11px] font-medium text-zinc-500 dark:text-zinc-400"
                  >
                    Or type any custom {displayGroupName} model ID (marked Unverified until tested)
                  </label>
                  <input
                    id={`custom-model-input-${provider}`}
                    type="text"
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder={modelsList[0]?.id || 'Enter exact model ID (e.g. gemini-4-hydrogen)'}
                    className="mt-1 w-full rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 font-mono text-xs text-zinc-950 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-white"
                  />
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
