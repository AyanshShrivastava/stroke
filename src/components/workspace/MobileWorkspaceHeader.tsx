import React from 'react';
import { ArrowLeft, FileCode2, Globe, MessageSquare, MoreHorizontal } from 'lucide-react';
import type { MistProject } from '../../types/mist';

interface MobileWorkspaceHeaderProps {
  project: MistProject;
  shortProviderLabel: string;
  activePane: 'chat' | 'preview';
  onBackHome: () => void;
  onSetActivePane: (pane: 'chat' | 'preview') => void;
  onOpenDeploy: () => void;
  onOpenMobileMore: () => void;
}

export default function MobileWorkspaceHeader({
  project,
  shortProviderLabel,
  activePane,
  onBackHome,
  onSetActivePane,
  onOpenDeploy,
  onOpenMobileMore,
}: MobileWorkspaceHeaderProps) {
  return (
    <header className="flex lg:hidden h-14 shrink-0 items-center justify-between border-b border-zinc-200 bg-white/95 px-3 backdrop-blur dark:border-zinc-800 dark:bg-[#0F0F12]/95">
      <div className="flex items-center gap-2 min-w-0">
        <button
          type="button"
          onClick={onBackHome}
          aria-label="Back to Websites"
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-zinc-200 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-800 cursor-pointer"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        </button>
        <div className="min-w-0">
          <h1 className="truncate font-display text-xs font-semibold text-zinc-950 dark:text-white">
            {project.name}
          </h1>
          <p className="truncate text-[10px] text-zinc-500">
            {project.files.length} files · {shortProviderLabel}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-1.5">
        <div className="flex items-center rounded-lg bg-zinc-100 p-0.5 dark:bg-zinc-900">
          <button
            type="button"
            onClick={() => onSetActivePane('chat')}
            className={`rounded-md p-1.5 text-xs font-medium cursor-pointer ${
              activePane === 'chat'
                ? 'bg-white text-zinc-950 shadow-sm dark:bg-zinc-800 dark:text-white'
                : 'text-zinc-500 hover:text-zinc-900 dark:text-zinc-400'
            }`}
            aria-label="Show AI Chat pane"
          >
            <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={() => onSetActivePane('preview')}
            className={`rounded-md p-1.5 text-xs font-medium cursor-pointer ${
              activePane === 'preview'
                ? 'bg-white text-zinc-950 shadow-sm dark:bg-zinc-800 dark:text-white'
                : 'text-zinc-500 hover:text-zinc-900 dark:text-zinc-400'
            }`}
            aria-label="Show Preview / Code pane"
          >
            <FileCode2 className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>

        <button
          type="button"
          onClick={onOpenDeploy}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl mist-primary-gradient px-3 text-xs font-medium text-white shadow-sm cursor-pointer"
        >
          <Globe className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Publish</span>
        </button>
        <button
          type="button"
          onClick={onOpenMobileMore}
          aria-label="Open workspace actions"
          className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-zinc-200 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-800 cursor-pointer"
        >
          <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
