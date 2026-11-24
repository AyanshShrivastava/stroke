import React from 'react';
import { AlertTriangle, CheckCircle2, Globe, Loader2 } from 'lucide-react';
import { motion } from 'motion/react';
import type { AiStreamProgress } from '../../types/mist';
import { MistMark } from '../MistLogo';

interface WorkspaceStreamCardProps {
  streamProgress: AiStreamProgress;
  refineElapsed: number;
  onCancelRefine: () => void;
}

function renderSearchBadge(progress: AiStreamProgress) {
  if (!progress.searchState || progress.searchState === 'idle') return null;

  const count = progress.searchSources?.length ?? 0;
  const label = progress.searchState === 'searching'
    ? 'Searching live web sources...'
    : progress.searchState === 'failed'
      ? 'Web search failed'
      : `Retrieved ${count} verified source${count === 1 ? '' : 's'}`;

  return (
    <div className="mt-2 rounded-lg border border-zinc-200/80 bg-white/80 px-2 py-1.5 text-[11px] dark:border-zinc-800 dark:bg-zinc-950/60">
      <span className="inline-flex items-center gap-1.5 font-medium text-zinc-800 dark:text-zinc-200">
        {progress.searchState === 'searching' ? (
          <Loader2 className="h-3 w-3 animate-spin text-(--mist-c2)" aria-hidden="true" />
        ) : progress.searchState === 'failed' ? (
          <AlertTriangle className="h-3 w-3 text-amber-500" aria-hidden="true" />
        ) : (
          <Globe className="h-3 w-3 text-emerald-500" aria-hidden="true" />
        )}
        <span>{label}</span>
      </span>
      {progress.searchError && (
        <p className="mt-0.5 text-[10px] text-amber-700 dark:text-amber-300">
          {progress.searchError}
        </p>
      )}
    </div>
  );
}

export default function WorkspaceStreamCard({
  streamProgress,
  refineElapsed,
  onCancelRefine,
}: WorkspaceStreamCardProps) {
  const activeLabel = streamProgress.activeFile
    ? `Editing ${streamProgress.activeFile}...`
    : streamProgress.phase;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      aria-live="polite"
      className="rounded-xl border border-(--mist-c2)/35 bg-gradient-to-br from-(--mist-c2)/10 to-(--mist-c3)/10 p-3 text-xs dark:border-(--mist-c2)/30 dark:from-(--mist-c2)/20 dark:to-(--mist-c3)/20"
    >
      <div className="relative h-1 w-full overflow-hidden rounded-full bg-(--mist-c2)/15 mb-2.5">
        <div className="mist-shimmer-bar absolute inset-y-0 left-0 w-1/2 rounded-full mist-primary-gradient" />
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 font-semibold text-zinc-950 dark:text-white truncate">
          <MistMark className="h-3.5 w-3.5 text-(--mist-c2) animate-pulse shrink-0" title="Refining" />
          <span className="truncate">{activeLabel}</span>
        </span>
        <div className="flex items-center gap-2 shrink-0">
          <span className="font-mono text-[10px] text-zinc-500 dark:text-zinc-400 tabular-nums">
            {refineElapsed}s
          </span>
          <button
            type="button"
            onClick={onCancelRefine}
            className="rounded border border-zinc-300/80 bg-white/90 px-1.5 py-0.5 text-[10px] font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 cursor-pointer"
          >
            Cancel
          </button>
        </div>
      </div>

      {renderSearchBadge(streamProgress)}

      {streamProgress.completedFiles.length > 0 && (
        <div className="mt-2 space-y-1 font-mono text-[11px]">
          {streamProgress.completedFiles.map((filePath) => (
            <div key={filePath} className="flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 className="h-3 w-3 shrink-0" aria-hidden="true" />
              <span className="truncate">{filePath}</span>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  );
}
