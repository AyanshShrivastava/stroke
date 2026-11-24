import * as Sentry from '@sentry/react';

const SENTRY_DSN =
  import.meta.env.VITE_SENTRY_DSN ||
  'https://d0c0e5b705103eb6df2c84e69fae200d@o4512470558769152.ingest.us.sentry.io/4512478355521536';

if (SENTRY_DSN) {
  Sentry.init({
    dsn: SENTRY_DSN,
    integrations: [
      Sentry.browserTracingIntegration(),
    ],
    tracesSampleRate: 1.0,
    tracePropagationTargets: ['localhost', /^\//, /^https:\/\/.*\.mist\.me/],
    environment: import.meta.env.MODE || 'development',
  });
}
