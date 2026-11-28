import React, { useState } from 'react';
import { Loader2, Terminal } from 'lucide-react';
import { motion } from 'motion/react';
import type { AiProviderConfig, AppAiMode, MistUser as User, StudioSettings } from '../../types/mist';
import type { ModelHealthIncident } from '../../utils/aiErrors';
import { maskApiKey } from '../../utils/projectOps';

interface SettingsAppAiSectionProps {
  user: User | null;
  studioSettings: StudioSettings;
  apiKey: string;
  providerDraft: AiProviderConfig;
  onUpdateSettings: (partial: Partial<StudioSettings>) => void;
  onIncident: (incident: ModelHealthIncident | null) => void;
}

const APP_AI_OPTIONS: Array<{ id: AppAiMode; title: string; desc: string }> = [
  {
    id: 'on_request',
    title: 'On Request Only',
    desc: 'Recommended — adds AI only when prompted.',
  },
  {
    id: 'off',
    title: 'Always Off',
    desc: 'Pure static / Canvas / Three.js builds.',
  },
  {
    id: 'always',
    title: 'Always Included',
    desc: 'Wire live App AI into every build.',
  },
];

async function runTestAppAiEndpoint(
  user: User,
  providerDraft: AiProviderConfig
): Promise<{ ok: boolean; message: string; incident: ModelHealthIncident | null }> {
  try {
    const idToken = await user.getIdToken();
    const resp = await fetch('/api/app-ai', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${idToken}`,
      },
      body: JSON.stringify({
        prompt: 'Confirm live app AI endpoint works in 8 words or less.',
        providerConfig: providerDraft,
      }),
    });
    const data = (await resp.json()) as {
      text?: string;
      error?: string;
      incident?: ModelHealthIncident;
    };
    if (!resp.ok || !data.text) {
      return {
        ok: false,
        message: data.incident?.message || data.error || 'App AI runtime test failed.',
        incident: data.incident || null,
      };
    }
    return {
      ok: true,
      message: data.text.trim(),
      incident: null,
    };
  } catch (err) {
    return {
      ok: false,
      message: err instanceof Error ? err.message : 'Network error calling /api/app-ai.',
      incident: null,
    };
  }
}

export default function SettingsAppAiSection({
  user,
  studioSettings,
  apiKey,
  providerDraft,
  onUpdateSettings,
  onIncident,
}: SettingsAppAiSectionProps) {
  const [isTestingAppAi, setIsTestingAppAi] = useState(false);
  const [appAiTestOutput, setAppAiTestOutput] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);

  const handleTestAppAiEndpoint = async () => {
    if (!user) {
      setAppAiTestOutput({
        ok: false,
        message: 'Sign in to Mist first to test /api/app-ai.',
      });
      return;
    }
    setIsTestingAppAi(true);
    setAppAiTestOutput(null);
    try {
      const res = await runTestAppAiEndpoint(user, providerDraft);
      onIncident(res.incident);
      setAppAiTestOutput({ ok: res.ok, message: res.message });
    } finally {
      setIsTestingAppAi(false);
    }
  };

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.08 }}
      aria-labelledby="settings-app-ai-heading"
      className="mist-surface-card rounded-2xl border border-zinc-200/90 p-5 sm:p-6 dark:border-zinc-800/90"
    >
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-600 to-fuchsia-500 text-white shadow-sm">
          <Terminal className="h-4 w-4" aria-hidden="true" />
        </div>
        <div>
          <h2
            id="settings-app-ai-heading"
            className="font-display text-base font-semibold text-zinc-950 dark:text-white"
          >
            AI Features Inside Generated Apps
          </h2>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed">
            Control when Mist integrates live <code className="font-mono text-zinc-800 dark:text-zinc-200">/api/app-ai</code> features into generated apps. Preview iframes use scoped ephemeral tokens and never expose your raw API key.
          </p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
        {APP_AI_OPTIONS.map((opt) => {
          const active = studioSettings.appAiMode === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() =>
                onUpdateSettings({
                  appAiMode: opt.id,
                  enableAppAi: opt.id === 'always',
                })
              }
              className={`rounded-xl border p-3 text-left transition-all cursor-pointer ${
                active
                  ? 'border-blue-600 bg-blue-500/10 text-zinc-950 dark:border-blue-500/70 dark:text-white'
                  : 'border-zinc-200 bg-white/60 text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-300 dark:hover:bg-zinc-900'
              }`}
            >
              <p className="font-semibold">{opt.title}</p>
              <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">{opt.desc}</p>
            </button>
          );
        })}
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-zinc-200/80 bg-zinc-50/90 p-3.5 text-xs dark:border-zinc-800 dark:bg-zinc-900/70">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-zinc-900 dark:text-zinc-100">
            Runtime Endpoint: <code className="font-mono text-blue-600 dark:text-blue-400">POST /api/app-ai</code>
          </p>
          <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
            Active Key:{' '}
            <span className="font-mono font-semibold text-zinc-800 dark:text-zinc-200">
              {maskApiKey(apiKey) || 'None configured'}
            </span>{' '}
            — automatically backs <code className="font-mono">window.mistAI.complete()</code> &amp; <code className="font-mono">window.mistAI.chat()</code> via secure session relay.
          </p>
        </div>
        <button
          type="button"
          disabled={isTestingAppAi || !apiKey.trim()}
          onClick={() => void handleTestAppAiEndpoint()}
          className="inline-flex w-full sm:w-auto justify-center min-h-[44px] sm:min-h-[38px] items-center gap-1.5 rounded-xl sm:rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-800 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700 transition-colors whitespace-nowrap shrink-0 cursor-pointer"
        >
          {isTestingAppAi && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          <span>Verify Runtime</span>
        </button>
      </div>

      {appAiTestOutput && (
        <div
          role="status"
          className={`mt-3 rounded-xl border p-3 text-xs ${
            appAiTestOutput.ok
              ? 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-200'
              : 'border-red-300 bg-red-50 text-red-900 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200'
          }`}
        >
          {appAiTestOutput.message}
        </div>
      )}
    </motion.section>
  );
}
