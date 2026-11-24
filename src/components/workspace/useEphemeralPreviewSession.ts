import { useEffect, useState } from 'react';
import type { MistUser as User, AiProviderConfig } from '../../types/mist';
import { mintSession, revokeSession, shouldMintPreviewSession } from './appAiRelay';

export function useEphemeralPreviewSession(
  hasAppAi: boolean,
  providerConfig: AiProviderConfig,
  user: User | null,
): string | null {
  const [sessionToken, setSessionToken] = useState<string | null>(null);

  useEffect(() => {
    if (!shouldMintPreviewSession(hasAppAi, providerConfig.apiKey, user) || !user) {
      setSessionToken(null);
      return;
    }

    let cancelled = false;
    let activeToken: string | null = null;
    let activeBearer = '';

    void mintSession(user, providerConfig).then((result) => {
      if (!result) {
        if (!cancelled) setSessionToken(null);
        return;
      }
      activeToken = result.token;
      activeBearer = result.bearer;
      if (cancelled) {
        revokeSession(activeToken, activeBearer);
      } else {
        setSessionToken(activeToken);
      }
    });

    return () => {
      cancelled = true;
      if (activeToken && activeBearer) {
        revokeSession(activeToken, activeBearer);
      }
    };
  }, [hasAppAi, providerConfig, user]);

  return sessionToken;
}
