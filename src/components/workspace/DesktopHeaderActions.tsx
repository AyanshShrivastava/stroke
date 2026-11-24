import React from 'react';
import {
  Copy,
  Cpu,
  Download,
  Globe,
  Mic,
  Monitor,
  Settings,
  Smartphone,
  Tablet,
  User as UserIcon,
} from 'lucide-react';
import type { MistUser as User, ViewportSize, WorkspaceViewMode } from '../../types/mist';
import { maskApiKey } from '../../utils/projectOps';

interface DesktopHeaderActionsProps {
  user: User | null;
  viewMode: WorkspaceViewMode;
  viewport: ViewportSize;
  shortProviderLabel: string;
  providerApiKey?: string;
  onSetViewport: (viewport: ViewportSize) => void;
  onOpenVoiceChat: () => void;
  onOpenProviders: () => void;
  onDuplicateProject: () => void;
  onExportZip: () => void;
  onOpenDeploy: () => void;
  onOpenSettings: () => void;
  onOpenAccount: () => void;
}

const VIEWPORTS = [
  { id: 'desktop', icon: Monitor, label: 'Desktop viewport' },
  { id: 'tablet', icon: Tablet, label: 'Tablet viewport' },
  { id: 'mobile', icon: Smartphone, label: 'Mobile viewport' },
] as const;

export default function DesktopHeaderActions({
  user,
  viewMode,
  viewport,
  shortProviderLabel,
  providerApiKey,
  onSetViewport,
  onOpenVoiceChat,
  onOpenProviders,
  onDuplicateProject,
  onExportZip,
  onOpenDeploy,
  onOpenSettings,
  onOpenAccount,
}: DesktopHeaderActionsProps) {
  const providerTooltip = maskApiKey(providerApiKey)
    ? `Active Key: ${maskApiKey(providerApiKey)}`
    : 'Add BYOK API key';

  return (
    <div className="flex items-center gap-1.5 shrink-0">
      {viewMode !== 'code' && (
        <div className="hidden xl:flex items-center gap-0.5 rounded-lg border border-zinc-200 p-0.5 dark:border-zinc-800">
          {VIEWPORTS.map(({ id, icon: Icon, label }) => (
            <button
              key={id}
              type="button"
              aria-label={label}
              onClick={() => onSetViewport(id)}
              className={`rounded-md p-1.5 transition-colors cursor-pointer ${
                viewport === id
                  ? 'bg-zinc-900 text-white dark:bg-zinc-700'
                  : 'text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white'
              }`}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={onOpenVoiceChat}
        aria-label="Open voice refinement studio"
        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-2 xl:px-2.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-800 transition-colors whitespace-nowrap shrink-0 cursor-pointer"
      >
        <Mic className="h-3.5 w-3.5 text-(--mist-c2)" aria-hidden="true" />
        <span className="hidden xl:inline">Voice</span>
      </button>

      <button
        type="button"
        onClick={onOpenProviders}
        aria-label="Configure AI models"
        title={providerTooltip}
        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-2.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-800 transition-colors whitespace-nowrap shrink-0 cursor-pointer"
      >
        <Cpu className="h-3.5 w-3.5 text-(--mist-c2)" aria-hidden="true" />
        <span className="max-w-[90px] truncate">{shortProviderLabel}</span>
      </button>

      <button
        type="button"
        onClick={onDuplicateProject}
        aria-label="Duplicate project"
        className="hidden xl:inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-2.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-800 transition-colors whitespace-nowrap shrink-0 cursor-pointer"
      >
        <Copy className="h-3.5 w-3.5" aria-hidden="true" />
        <span>Duplicate</span>
      </button>

      <button
        type="button"
        onClick={onExportZip}
        aria-label="Export ZIP"
        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-2 xl:px-3 text-xs font-medium text-zinc-800 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800 transition-colors whitespace-nowrap shrink-0 cursor-pointer"
      >
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="hidden xl:inline">Export ZIP</span>
      </button>

      <button
        type="button"
        onClick={onOpenDeploy}
        className="inline-flex h-8 items-center gap-1.5 rounded-lg mist-primary-gradient px-3 text-xs font-medium text-white shadow-sm transition-all whitespace-nowrap shrink-0 cursor-pointer"
      >
        <Globe className="h-3.5 w-3.5" aria-hidden="true" />
        <span>Publish</span>
      </button>

      <button
        type="button"
        onClick={onOpenSettings}
        aria-label="Open Studio Settings"
        className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-200 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-800 transition-colors shrink-0 cursor-pointer"
      >
        <Settings className="h-3.5 w-3.5" aria-hidden="true" />
      </button>

      <button
        type="button"
        onClick={onOpenAccount}
        aria-label="Account profile"
        className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-200 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-800 transition-colors shrink-0 cursor-pointer overflow-hidden"
      >
        {user?.photoURL ? (
          <img src={user.photoURL} alt={user.displayName || 'Account'} className="h-full w-full object-cover" referrerPolicy="no-referrer" />
        ) : (
          <UserIcon className="h-3.5 w-3.5" aria-hidden="true" />
        )}
      </button>
    </div>
  );
}
