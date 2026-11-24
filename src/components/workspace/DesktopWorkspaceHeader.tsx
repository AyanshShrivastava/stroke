import React, { useState } from 'react';
import {
  ArrowLeft,
  Columns2,
  Eye,
  MousePointerClick,
  Code2,
} from 'lucide-react';
import type { MistUser as User, MistProject, ViewportSize, WorkspaceViewMode } from '../../types/mist';
import MistLogo from '../MistLogo';
import DesktopHeaderActions from './DesktopHeaderActions';

interface DesktopWorkspaceHeaderProps {
  user: User | null;
  project: MistProject;
  viewMode: WorkspaceViewMode;
  viewport: ViewportSize;
  shortProviderLabel: string;
  providerApiKey?: string;
  onBackHome: () => void;
  onUpdateProjectName: (name: string) => void;
  onSetViewMode: (mode: WorkspaceViewMode) => void;
  onSetViewport: (viewport: ViewportSize) => void;
  onOpenVoiceChat: () => void;
  onOpenProviders: () => void;
  onDuplicateProject: () => void;
  onExportZip: () => void;
  onOpenDeploy: () => void;
  onOpenSettings: () => void;
  onOpenAccount: () => void;
}

const VIEW_MODES = [
  { id: 'preview', label: 'Preview', icon: Eye },
  { id: 'visual', label: 'Visual', icon: MousePointerClick },
  { id: 'code', label: 'Code', icon: Code2 },
  { id: 'split', label: 'Split', icon: Columns2 },
] as const;

export default function DesktopWorkspaceHeader({
  user,
  project,
  viewMode,
  viewport,
  shortProviderLabel,
  providerApiKey,
  onBackHome,
  onUpdateProjectName,
  onSetViewMode,
  onSetViewport,
  onOpenVoiceChat,
  onOpenProviders,
  onDuplicateProject,
  onExportZip,
  onOpenDeploy,
  onOpenSettings,
  onOpenAccount,
}: DesktopWorkspaceHeaderProps) {
  const [titleSavedToast, setTitleSavedToast] = useState(false);

  return (
    <header className="hidden lg:flex h-14 shrink-0 items-center justify-between gap-2 xl:gap-3 border-b border-zinc-200 bg-white px-3 xl:px-4 dark:border-zinc-800 dark:bg-[#0F0F12]">
      <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
        <button
          type="button"
          onClick={onBackHome}
          aria-label="Back to Websites"
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-zinc-200 px-2.5 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-800 transition-colors whitespace-nowrap shrink-0 cursor-pointer"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Back</span>
          <span className="text-zinc-300 dark:text-zinc-700">·</span>
          <MistLogo size="xs" showWordmark={false} />
          <span className="font-display font-bold text-black dark:text-white">Mist</span>
        </button>

        <span className="text-zinc-300 dark:text-zinc-700 shrink-0">/</span>

        <input
          type="text"
          aria-label="Project name"
          value={project.name}
          onChange={(e) => onUpdateProjectName(e.target.value)}
          onBlur={() => {
            setTitleSavedToast(true);
            setTimeout(() => setTitleSavedToast(false), 1200);
          }}
          className="min-w-[72px] max-w-[140px] xl:max-w-[190px] flex-1 truncate rounded-md border border-transparent bg-transparent px-1.5 py-1 font-display text-xs xl:text-sm font-semibold text-zinc-950 hover:border-zinc-200 focus:border-(--mist-c2) focus:bg-white focus:outline-none dark:text-white dark:hover:border-zinc-700 dark:focus:bg-zinc-900"
        />

        {titleSavedToast && (
          <span className="hidden xl:inline text-[11px] text-emerald-600 dark:text-emerald-400 whitespace-nowrap shrink-0">
            Saved
          </span>
        )}
      </div>

      {/* Center View Mode Switcher */}
      <div
        role="tablist"
        aria-label="Workspace view mode"
        className="flex shrink-0 items-center gap-0.5 sm:gap-1 rounded-lg bg-zinc-100 p-0.5 sm:p-1 dark:bg-zinc-900"
      >
        {VIEW_MODES.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            role="tab"
            aria-selected={viewMode === id}
            aria-label={label}
            type="button"
            onClick={() => onSetViewMode(id)}
            className={`inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
              viewMode === id
                ? 'bg-white text-zinc-950 shadow-sm dark:bg-zinc-800 dark:text-white'
                : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-white'
            }`}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
      </div>

      <DesktopHeaderActions
        user={user}
        viewMode={viewMode}
        viewport={viewport}
        shortProviderLabel={shortProviderLabel}
        providerApiKey={providerApiKey}
        onSetViewport={onSetViewport}
        onOpenVoiceChat={onOpenVoiceChat}
        onOpenProviders={onOpenProviders}
        onDuplicateProject={onDuplicateProject}
        onExportZip={onExportZip}
        onOpenDeploy={onOpenDeploy}
        onOpenSettings={onOpenSettings}
        onOpenAccount={onOpenAccount}
      />
    </header>
  );
}
