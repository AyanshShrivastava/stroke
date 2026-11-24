import './instrument.ts';
import { createRoot } from 'react-dom/client';
import { ClerkProvider } from '@clerk/react';
import App from './App.tsx';
import { mistClerkAppearance } from './utils/clerkTheme.ts';
import './index.css';

const clerkPublishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

function ClerkConfigurationError() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#090b10] px-6 text-white">
      <div className="max-w-xl rounded-2xl border border-white/10 bg-white/5 p-6">
        <h1 className="text-xl font-semibold">Clerk configuration required</h1>
        <p className="mt-3 text-sm text-white/70">
          Set <code>VITE_CLERK_PUBLISHABLE_KEY</code> in the environment and restart Mist.
        </p>
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
