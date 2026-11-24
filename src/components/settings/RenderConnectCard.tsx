import React, { useState } from 'react';
import { CheckCircle2, ExternalLink, Eye, EyeOff, Loader2 } from 'lucide-react';
import { mistApi } from '../../utils/apiClient';

interface RenderConnectCardProps {
  onConnected: () => Promise<void>;
}

export default function RenderConnectCard({ onConnected }: RenderConnectCardProps) {
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const key = apiKeyInput.trim();
    if (!key) {
      setError('Please enter your Render API key.');
      return;
    }
    if (!key.startsWith('rnd_')) {
      setError('Render API keys must begin with "rnd_".');
      return;
    }
    setIsConnecting(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await mistApi.connectRender(key);
      setApiKeyInput('');
      await onConnected();
      setSuccess(`Connected to Render workspace "${res.owner.name}".`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to connect Render account.');
    } finally {
      setIsConnecting(false);
    }
  };

  return (
    <div className="space-y-3 rounded-xl border border-zinc-200/80 bg-zinc-50/90 p-4 dark:border-zinc-800 dark:bg-zinc-900/70">
      <div className="flex items-center justify-between">
        <p className="font-medium text-zinc-800 dark:text-zinc-200">
          Connect with API Key
        </p>
        <a
          href="https://dashboard.render.com/u/settings#api-keys"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-[11px] font-medium text-blue-600 hover:underline dark:text-blue-400"
        >
          <span>Create API Key</span>
          <ExternalLink className="h-3 w-3" />
        </a>
      </div>

      <p className="text-[11px] text-zinc-600 dark:text-zinc-400 leading-relaxed">
        Mist connects to your personal Render account to spin up and manage static site services. Keys must start with <code className="font-mono text-xs">rnd_</code> and are encrypted server-side with AES-256-GCM authenticated encryption.
      </p>

      <form onSubmit={handleSubmit} className="space-y-3 pt-1">
        <div className="relative">
          <input
            type={showKey ? 'text' : 'password'}
            value={apiKeyInput}
            onChange={(e) => setApiKeyInput(e.target.value)}
            placeholder="rnd_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            className="w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 pr-10 font-mono text-xs text-zinc-950 placeholder-zinc-400 focus:border-blue-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-white"
          />
          <button
            type="button"
            onClick={() => setShowKey(!showKey)}
            className="absolute right-2.5 top-2.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 cursor-pointer"
            aria-label={showKey ? 'Hide key' : 'Show key'}
          >
            {showKey ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
          </button>
        </div>

        {error && (
          <p className="rounded-lg bg-red-50 p-2 text-[11px] text-red-700 dark:bg-red-950/60 dark:text-red-300">
            {error}
          </p>
        )}

        {success && (
          <p className="rounded-lg bg-emerald-50 p-2 text-[11px] text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300">
            {success}
          </p>
        )}

        <button
          type="submit"
          disabled={isConnecting}
          className="inline-flex min-h-[34px] items-center gap-1.5 rounded-lg mist-primary-gradient px-3 py-1.5 text-[11px] font-medium text-white shadow-sm disabled:opacity-50 cursor-pointer"
        >
          {isConnecting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5" />
          )}
          <span>{isConnecting ? 'Verifying Key...' : 'Connect Render'}</span>
        </button>
      </form>
    </div>
  );
}
