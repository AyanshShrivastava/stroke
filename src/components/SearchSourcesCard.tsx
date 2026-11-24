import React, { useState } from 'react';
import {
  AlertTriangle,
  Calendar,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Globe,
  Search,
} from 'lucide-react';
import type { WebSearchOutcome } from '../types/mist';
import { sanitizeSearchText, sanitizeSearchUrl } from '../data/webSearch';

interface SearchSourcesCardProps {
  outcome: WebSearchOutcome;
  compact?: boolean;
}

export default function SearchSourcesCard({ outcome, compact = false }: SearchSourcesCardProps) {
  const [expanded, setExpanded] = useState(!compact);

  if (!outcome || outcome.status === 'skipped') {
    return null;
  }

  if (outcome.status === 'failed') {
    return (
      <div
        role="status"
        className="mt-2.5 rounded-xl border border-amber-300/80 bg-amber-50/90 p-2.5 text-[11px] text-amber-950 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-200"
      >
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
          <div className="min-w-0 flex-1 space-y-1">
            <p className="font-semibold">
              Web research failed — response generated without live web results
            </p>
            {outcome.error && (
              <p className="text-[11px] opacity-90 break-words">
                {sanitizeSearchText(outcome.error, 260)}
              </p>
            )}
            {outcome.queries.length > 0 && (
              <p className="font-mono text-[10px] opacity-75 truncate">
                Attempted: {outcome.queries.join(' · ')}
              </p>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (outcome.status === 'cancelled') {
    return (
      <div className="mt-2.5 rounded-xl border border-zinc-200 bg-zinc-50 p-2.5 text-[11px] text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/70 dark:text-zinc-400">
        Web search was cancelled before completion.
      </div>
    );
  }

  const citedSet = new Set((outcome.citedIds || []).map((id) => id.toUpperCase()));
  const validSources = outcome.sources
    .map((s) => {
      const safeHref = sanitizeSearchUrl(s.url);
      if (!safeHref) return null;
      return {
        ...s,
        safeHref,
        safeTitle: sanitizeSearchText(s.title, 180) || s.hostname || safeHref,
        safeSnippet: sanitizeSearchText(s.snippet, 320),
        safeDate: s.publishedDate ? sanitizeSearchText(s.publishedDate, 48) : undefined,
      };
    })
    .filter((s): s is NonNullable<typeof s> => Boolean(s));

  if (outcome.status === 'no_results' || validSources.length === 0) {
    return (
      <div className="mt-2.5 rounded-xl border border-zinc-200 bg-zinc-50/90 p-2.5 text-[11px] text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950/70 dark:text-zinc-400">
        <div className="flex items-center gap-1.5 font-medium text-zinc-800 dark:text-zinc-200">
          <Search className="h-3 w-3 text-zinc-500" aria-hidden="true" />
          <span>No matching web sources found</span>
        </div>
        {outcome.queries.length > 0 && (
          <p className="mt-1 font-mono text-[10px] opacity-80 truncate">
            Searched: {outcome.queries.join(' · ')}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="mt-2.5 rounded-xl border border-zinc-200/90 bg-zinc-50/85 p-2.5 text-[11px] dark:border-zinc-800 dark:bg-zinc-950/70">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left font-medium text-zinc-800 dark:text-zinc-200 cursor-pointer"
        >
          <Globe className="h-3.5 w-3.5 shrink-0 text-blue-600 dark:text-blue-400" aria-hidden="true" />
          <span className="truncate">
            Retrieved Web Sources ({validSources.length})
          </span>
          {outcome.providerName && (
            <span className="hidden sm:inline text-[10px] font-normal text-zinc-500 dark:text-zinc-400 truncate">
              · {sanitizeSearchText(outcome.providerName, 40)}
            </span>
          )}
          <span className="ml-auto text-zinc-400">
            {expanded ? (
              <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
            )}
          </span>
        </button>
      </div>

      {outcome.warning && (
        <p className="mt-1 text-[10px] text-amber-700 dark:text-amber-300">
          {sanitizeSearchText(outcome.warning, 180)}
        </p>
      )}

      {expanded && (
        <div className="mt-2 space-y-2 border-t border-zinc-200/80 pt-2 dark:border-zinc-800/80">
          {outcome.queries.length > 0 && (
            <p className="font-mono text-[10px] text-zinc-500 dark:text-zinc-400 break-words">
              Queries: {outcome.queries.join(' · ')}
            </p>
          )}

          <div className="space-y-1.5">
            {validSources.map((src) => {
              const isCited = citedSet.has(src.id.toUpperCase());
              return (
                <a
                  key={src.id}
                  href={src.safeHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`block rounded-lg border p-2 transition-colors ${
                    isCited
                      ? 'border-blue-300/80 bg-white hover:border-blue-400 dark:border-blue-800/70 dark:bg-zinc-900 dark:hover:border-blue-600'
                      : 'border-zinc-200/80 bg-white/80 hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900/60 dark:hover:border-zinc-700'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="inline-flex shrink-0 items-center rounded bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-white dark:bg-zinc-100 dark:text-zinc-950">
                        [{src.id}]
                      </span>
                      <span className="font-semibold text-zinc-900 dark:text-zinc-100 truncate">
                        {src.safeTitle}
                      </span>
                    </div>
                    <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-zinc-400" aria-hidden="true" />
                  </div>

                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-zinc-500 dark:text-zinc-400">
                    {src.hostname && <span className="font-mono truncate">{src.hostname}</span>}
                    {src.safeDate && (
                      <span className="inline-flex items-center gap-1">
                        <Calendar className="h-2.5 w-2.5" aria-hidden="true" />
                        <span>{src.safeDate}</span>
                      </span>
                    )}
                    {isCited && (
                      <span className="font-semibold text-blue-600 dark:text-blue-400">
                        Cited in summary
                      </span>
                    )}
                  </div>

                  {src.safeSnippet && (
                    <p className="mt-1 text-[11px] leading-snug text-zinc-600 dark:text-zinc-400 line-clamp-2">
                      {src.safeSnippet}
                    </p>
                  )}
                </a>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
