import React, { useState } from 'react';
import { CheckCircle2, Loader2, LogOut, Server } from 'lucide-react';
import { motion } from 'motion/react';
import type { MistUser as User } from '../../types/mist';
import { mistApi } from '../../utils/apiClient';
import RenderConnectCard from './RenderConnectCard';

interface SettingsHostingSectionProps {
  user: User | null;
  renderStatus: {
    connected: boolean;
    keyHint?: string;
    ownerId?: string;
    ownerName?: string;
    ownerEmail?: string;
    workspaceType?: string;
    connectedAt?: string;
  } | null;
  renderLoading: boolean;
  onRefreshStatus: () => Promise<void>;
}

function HostingNotSignedInCard() {
  return (
    <p className="rounded-xl border border-zinc-200/80 bg-zinc-50/90 p-3.5 text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/70 dark:text-zinc-400 leading-relaxed">
      Sign in to Mist to securely encrypt your Render API key in your server-side credential vault.
    </p>
  );
}

function HostingLoadingCard() {
  return (
    <div className="flex items-center justify-center py-4 text-zinc-500">
      <Loader2 className="h-4 w-4 animate-spin mr-2" />
      <span>Checking hosting connection status...</span>
    </div>
  );
}

function HostingConnectedCard({
  renderStatus,
  isDisconnecting,
  renderError,
  onDisconnect,
}: {
  renderStatus: NonNullable<SettingsHostingSectionProps['renderStatus']>;
  isDisconnecting: boolean;
  renderError: string | null;
  onDisconnect: () => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between rounded-xl border border-emerald-200 bg-emerald-50/80 p-3.5 dark:border-emerald-900/60 dark:bg-emerald-950/30">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-emerald-950 dark:text-emerald-100">
              {renderStatus.ownerName || 'Personal Workspace'}
            </span>
            {renderStatus.workspaceType ? (
              <span className="rounded bg-emerald-200/70 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-emerald-900 dark:bg-emerald-900/70 dark:text-emerald-300">
                {renderStatus.workspaceType}
              </span>
            ) : null}
          </div>
          <p className="mt-0.5 font-mono text-[11px] text-emerald-800 dark:text-emerald-300">
            Key: {renderStatus.keyHint || 'rnd_••••••••'}
          </p>
        </div>

        <button
          type="button"
          disabled={isDisconnecting}
          onClick={onDisconnect}
          className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white px-3 py-1.5 text-[11px] font-medium text-red-600 hover:bg-red-50 dark:border-red-900/60 dark:bg-zinc-900 dark:text-red-400 dark:hover:bg-red-950/40 cursor-pointer disabled:opacity-50"
        >
          {isDisconnecting ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <LogOut className="h-3 w-3" />
          )}
          <span>Disconnect</span>
        </button>
      </div>

      {renderError ? (
        <p className="rounded-lg bg-red-50 p-2 text-[11px] text-red-700 dark:bg-red-950/60 dark:text-red-300">
          {renderError}
        </p>
      ) : null}

      <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
        Your Render API key is encrypted using AES-256-GCM in your personal credential vault. You can now deploy websites directly to Render from the Publish dialog in any project.
      </p>
    </div>
  );
}

export default function SettingsHostingSection({
  user,
  renderStatus,
  renderLoading,
  onRefreshStatus,
}: SettingsHostingSectionProps) {
  const [isDisconnectingRender, setIsDisconnectingRender] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);

  const handleDisconnect = async () => {
    setIsDisconnectingRender(true);
    setRenderError(null);
    try {
      await mistApi.disconnectRender();
      await onRefreshStatus();
    } catch (err) {
      setRenderError(err instanceof Error ? err.message : 'Failed to disconnect Render account.');
    } finally {
      setIsDisconnectingRender(false);
    }
  };

  const isConnected = Boolean(renderStatus?.connected);

  const renderContent = () => {
    if (!user) {
      return <HostingNotSignedInCard />;
    }
    if (renderLoading) {
      return <HostingLoadingCard />;
    }
    if (renderStatus?.connected) {
      return (
        <HostingConnectedCard
          renderStatus={renderStatus}
          isDisconnecting={isDisconnectingRender}
          renderError={renderError}
          onDisconnect={handleDisconnect}
        />
      );
    }
    return <RenderConnectCard onConnected={onRefreshStatus} />;
  };

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.14 }}
      aria-labelledby="settings-hosting-heading"
      className="mist-surface-card rounded-2xl border border-zinc-200/90 p-5 sm:p-6 dark:border-zinc-800/90"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-sm">
            <Server className="h-4 w-4" aria-hidden="true" />
          </div>
          <div>
            <h2
              id="settings-hosting-heading"
              className="font-display text-base font-semibold text-zinc-950 dark:text-white"
            >
              Connected Hosting (Render)
            </h2>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Deploy your generated websites to your personal Render account
            </p>
          </div>
        </div>

        {isConnected ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-2.5 py-0.5 text-[10px] font-semibold text-emerald-800 dark:bg-emerald-950/70 dark:text-emerald-300">
            <CheckCircle2 className="h-3 w-3" />
            <span>Connected</span>
          </span>
        ) : null}
      </div>

      <div className="mt-4 space-y-4 text-xs">
        {renderContent()}
      </div>
    </motion.section>
  );
}