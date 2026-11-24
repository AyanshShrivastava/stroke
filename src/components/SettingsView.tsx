import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  LogOut,
  Moon,
  Sun,
  User as UserIcon,
} from 'lucide-react';
import { motion } from 'motion/react';
import type { MistUser as User } from '../types/mist';
import type {
  AiProviderConfig,
  DeploymentRecord,
  MistProject,
  StudioSettings,
  WebSearchConfig,
} from '../types/mist';
import type { ModelHealthIncident } from '../utils/aiErrors';
import MistLogo from './MistLogo';
import { mistApi } from '../utils/apiClient';
import SettingsAiSection from './settings/SettingsAiSection';
import SettingsWebSearchSection from './settings/SettingsWebSearchSection';
import SettingsAppAiSection from './settings/SettingsAppAiSection';
import SettingsAccountSection from './settings/SettingsAccountSection';
import SettingsHostingSection from './settings/SettingsHostingSection';
import SettingsAppearanceSection from './settings/SettingsAppearanceSection';

interface SettingsViewProps {
  user: User | null;
  projects: MistProject[];
  deployments: DeploymentRecord[];
  providerConfig: AiProviderConfig;
  webSearchConfig: WebSearchConfig;
  studioSettings: StudioSettings;
  modelIncident: ModelHealthIncident | null;
  onBack: () => void;
  onSaveProvider: (next: AiProviderConfig) => void;
  onSaveWebSearch: (next: WebSearchConfig) => void;
  onUpdateSettings: (partial: Partial<StudioSettings>) => void;
  onIncident: (incident: ModelHealthIncident | null) => void;
  onSignIn: () => void;
  onSignOut: () => void;
}

export default function SettingsView({
  user,
  projects,
  deployments,
  providerConfig,
  webSearchConfig,
  studioSettings,
  modelIncident,
  onBack,
  onSaveProvider,
  onSaveWebSearch,
  onUpdateSettings,
  onIncident,
  onSignIn,
  onSignOut,
}: SettingsViewProps) {
  const [renderStatus, setRenderStatus] = useState<{
    connected: boolean;
    keyHint?: string;
    ownerId?: string;
    ownerName?: string;
    ownerEmail?: string;
    workspaceType?: string;
    connectedAt?: string;
  } | null>(null);
  const [renderLoading, setRenderLoading] = useState(false);

  const fetchRenderStatus = useCallback(async () => {
    if (!user) {
      setRenderStatus(null);
      return;
    }
    setRenderLoading(true);
    try {
      const res = await mistApi.getRenderStatus();
      setRenderStatus(res);
    } catch {
      setRenderStatus({ connected: false });
    } finally {
      setRenderLoading(false);
    }
  }, [user]);

  useEffect(() => {
    void fetchRenderStatus();
  }, [fetchRenderStatus]);

  const darkMode = studioSettings.theme === 'dark';

  return (
    <div className="mist-ambient-canvas min-h-screen text-[#09090B] dark:text-[#FAFAFA] flex flex-col">
      {/* Studio Top Bar */}
      <header className="sticky top-0 z-30 border-b border-zinc-200/80 bg-[#FAFAFA]/85 backdrop-blur-xl dark:border-zinc-800/80 dark:bg-[#09090B]/80">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 sm:px-6 h-14">
          <div className="flex items-center gap-3 min-w-0">
            <button
              type="button"
              onClick={onBack}
              className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-zinc-200 bg-white/80 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900/80 dark:text-zinc-200 dark:hover:bg-zinc-800 transition-colors whitespace-nowrap shrink-0 cursor-pointer"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Back</span>
            </button>
            <div className="flex items-center gap-2 min-w-0">
              <MistLogo size="sm" showWordmark={false} />
              <span className="hidden sm:inline font-display text-base font-bold text-black dark:text-white">
                Mist
              </span>
              <span className="hidden sm:inline text-zinc-300 dark:text-zinc-700">/</span>
              <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300 truncate">
                Settings
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => onUpdateSettings({ theme: darkMode ? 'light' : 'dark' })}
              aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
              className="inline-flex h-10 w-10 sm:h-9 sm:w-9 items-center justify-center rounded-xl border border-zinc-200 bg-white/80 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900/80 dark:text-zinc-300 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
            >
              {darkMode ? (
                <Sun className="h-4 w-4" aria-hidden="true" />
              ) : (
                <Moon className="h-4 w-4" aria-hidden="true" />
              )}
            </button>

            {user ? (
              <button
                type="button"
                onClick={onSignOut}
                className="inline-flex min-h-[40px] sm:min-h-[36px] items-center gap-1.5 rounded-xl border border-zinc-200 bg-white/80 px-3 py-1.5 text-xs font-medium text-zinc-800 hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900/80 dark:text-zinc-200 dark:hover:bg-zinc-800 transition-colors whitespace-nowrap shrink-0 cursor-pointer"
              >
                <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Sign Out</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={onSignIn}
                className="inline-flex min-h-[40px] sm:min-h-[36px] items-center gap-1.5 rounded-xl mist-primary-gradient px-3.5 py-1.5 text-xs font-medium text-white shadow-sm transition-all whitespace-nowrap shrink-0 cursor-pointer"
              >
                <UserIcon className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Sign In</span>
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 sm:px-6 py-8 sm:py-10 space-y-6">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
        >
          <h1 className="font-display text-2xl sm:text-3xl font-semibold tracking-tight text-zinc-950 dark:text-white">
            Studio Settings
          </h1>
          <p className="mt-1.5 text-sm text-zinc-600 dark:text-zinc-400">
            Configure your BYOK AI endpoints, in-app AI runtime, account preferences, and editor defaults.
          </p>
        </motion.div>

        {modelIncident && (
          <div
            role="alert"
            className="flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50/90 p-4 text-xs text-amber-950 dark:border-amber-700/60 dark:bg-amber-950/45 dark:text-amber-200"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
            <div>
              <p className="font-semibold">{modelIncident.title}</p>
              <p className="mt-0.5 opacity-90">{modelIncident.message}</p>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Left Primary Column: AI, Search & App AI */}
          <div className="lg:col-span-7 space-y-6">
            <SettingsAiSection
              user={user}
              providerConfig={providerConfig}
              onSaveProvider={onSaveProvider}
              onIncident={onIncident}
            />

            <SettingsWebSearchSection
              user={user}
              webSearchConfig={webSearchConfig}
              studioSettings={studioSettings}
              onSaveWebSearch={onSaveWebSearch}
              onUpdateSettings={onUpdateSettings}
            />

            <SettingsAppAiSection
              user={user}
              studioSettings={studioSettings}
              apiKey={providerConfig.apiKey || ''}
              providerDraft={providerConfig}
              onUpdateSettings={onUpdateSettings}
              onIncident={onIncident}
            />
          </div>

          {/* Right Secondary Column: Account, Hosting & Appearance */}
          <div className="lg:col-span-5 space-y-6">
            <SettingsAccountSection
              user={user}
              projects={projects}
              deployments={deployments}
              onSignIn={onSignIn}
            />

            <SettingsHostingSection
              user={user}
              renderStatus={renderStatus}
              renderLoading={renderLoading}
              onRefreshStatus={fetchRenderStatus}
            />

            <SettingsAppearanceSection
              user={user}
              studioSettings={studioSettings}
              onUpdateSettings={onUpdateSettings}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
