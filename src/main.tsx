import './instrument.ts';
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ClerkProvider } from '@clerk/react';
import App from './App.tsx';
import { mistClerkAppearance } from './utils/clerkTheme.ts';
import './index.css';

const clerkPublishableKey =
  import.meta.env.VITE_CLERK_PUBLISHABLE_KEY ||
  (typeof window !== 'undefined' ? localStorage.getItem('mist_clerk_pub_key') : null);

function ClerkConfigurationError() {
  const [keyInput, setKeyInput] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleSave = (key: string) => {
    const trimmed = key.trim();
    if (!trimmed.startsWith('pk_test_') && !trimmed.startsWith('pk_live_')) {
      setError('Key must start with pk_test_ or pk_live_');
      return;
    }
    localStorage.setItem('mist_clerk_pub_key', trimmed);
    window.location.reload();
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#090b10] px-6 text-white selection:bg-pink-500 selection:text-white">
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur-xl shadow-2xl">
        <div className="flex items-center gap-3 mb-4">
          <div className="h-8 w-8 rounded-lg bg-pink-500/20 border border-pink-500/30 flex items-center justify-center text-pink-400 font-bold text-sm">
            M
          </div>
          <h1 className="text-lg font-semibold tracking-tight text-white">Mist — Authentication Setup</h1>
        </div>
        <p className="text-xs text-white/70 leading-relaxed">
          Clerk is the sole identity provider for Mist. Provide your Clerk Publishable Key or launch with local development defaults.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSave(keyInput);
          }}
          className="mt-5 space-y-3"
        >
          <div>
            <label className="block text-xs font-medium text-white/80 mb-1.5">
              Clerk Publishable Key
            </label>
            <input
              type="text"
              value={keyInput}
              onChange={(e) => {
                setKeyInput(e.target.value);
                setError(null);
              }}
              placeholder="pk_test_... or pk_live_..."
              className="w-full rounded-xl border border-white/10 bg-white/5 px-3.5 py-2.5 text-xs text-white placeholder-white/30 focus:border-pink-500/50 focus:outline-none focus:ring-1 focus:ring-pink-500/50 transition-all font-mono"
            />
          </div>

          {error && <p className="text-xs text-red-400 font-medium">{error}</p>}

          <div className="flex flex-col gap-2 pt-2">
            <button
              type="submit"
              disabled={!keyInput.trim()}
              className="w-full rounded-xl bg-pink-500 px-4 py-2.5 text-xs font-semibold text-white hover:bg-pink-400 disabled:opacity-50 transition-all cursor-pointer shadow-lg shadow-pink-500/20"
            >
              Save Key & Launch Mist
            </button>
            {import.meta.env.DEV && (
              <button
                type="button"
                onClick={() => handleSave('pk_test_Y2xlcmsuaW5zcGlyZWQucHVtYS03NC5sY2wuZGV2JA')}
                className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-xs font-medium text-white/80 hover:bg-white/[0.08] hover:text-white transition-all cursor-pointer"
              >
                Launch with Development Key
              </button>
            )}
          </div>
        </form>
      </div>
    </main>
  );
}

const root = createRoot(document.getElementById('root')!);

if (!clerkPublishableKey) {
  root.render(<ClerkConfigurationError />);
} else {
  root.render(
    <ClerkProvider
      publishableKey={clerkPublishableKey}
      afterSignOutUrl="/"
      appearance={mistClerkAppearance}
    >
      <App />
    </ClerkProvider>,
  );
}
