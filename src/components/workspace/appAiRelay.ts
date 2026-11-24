import type { MistUser as User, AiProviderConfig } from '../../types/mist';
import type { ModelHealthIncident } from '../../utils/aiErrors';

export interface AppAiResponseData {
  text?: string;
  provider?: string;
  model?: string;
  error?: string;
  incident?: ModelHealthIncident;
}

export interface RelayParams {
  reqId: string;
  payload: Record<string, unknown>;
  user: User | null;
  hasAppAi: boolean;
  providerConfig: AiProviderConfig;
  sessionToken: string | null;
  targetWindow: Window;
}

export function createAppAiRequestBody(
  payload: Record<string, unknown>,
  sessionToken: string | null,
  providerConfig: AiProviderConfig,
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    prompt: typeof payload.prompt === 'string' ? payload.prompt : undefined,
    messages: Array.isArray(payload.messages) ? payload.messages : undefined,
    systemInstruction:
      typeof payload.systemInstruction === 'string' ? payload.systemInstruction : undefined,
    jsonMode: Boolean(payload.jsonMode),
  };
  if (sessionToken) {
    body.sessionToken = sessionToken;
  } else {
    body.providerConfig = providerConfig;
  }
  return body;
}

export function postBridgeResponse(
  targetWindow: Window,
  reqId: string,
  data: { ok: boolean; text?: string; provider?: string; model?: string; error?: string },
): void {
  targetWindow.postMessage({ type: 'MIST_APP_AI_RESPONSE', requestId: reqId, ...data }, '*');
}

export function validateAppAiPrerequisites(hasAppAi: boolean, user: User | null): User {
  if (!hasAppAi) {
    throw new Error('Live App AI is disabled for this project.');
  }
  if (!user) {
    throw new Error('Sign in with Google in Mist before using App AI in preview.');
  }
  return user;
}

export function getErrorMessage(data: AppAiResponseData): string {
  if (data.incident?.message) return data.incident.message;
  if (data.error) return data.error;
  return 'App AI request failed.';
}

export function getCaughtErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'App AI relay failed.';
}

export async function relayAppAiRequest(params: RelayParams): Promise<void> {
  try {
    const user = validateAppAiPrerequisites(params.hasAppAi, params.user);
    const idToken = await user.getIdToken();
    const requestBody = createAppAiRequestBody(params.payload, params.sessionToken, params.providerConfig);

    const resp = await fetch('/api/app-ai', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${idToken}`,
      },
      body: JSON.stringify(requestBody),
    });

    const data = (await resp.json()) as AppAiResponseData;

    if (!resp.ok || !data.text) {
      postBridgeResponse(params.targetWindow, params.reqId, {
        ok: false,
        error: getErrorMessage(data),
      });
      return;
    }

    postBridgeResponse(params.targetWindow, params.reqId, {
      ok: true,
      text: data.text,
      provider: data.provider,
      model: data.model,
    });
  } catch (err) {
    postBridgeResponse(params.targetWindow, params.reqId, {
      ok: false,
      error: getCaughtErrorMessage(err),
    });
  }
}

export async function mintSession(
  user: User,
  providerConfig: AiProviderConfig,
): Promise<{ token: string; bearer: string } | null> {
  const idToken = await user.getIdToken();
  const bearer = `Bearer ${idToken}`;
  const resp = await fetch('/api/ai/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: bearer },
    body: JSON.stringify({ providerConfig }),
  });
  if (!resp.ok) return null;
  const data = (await resp.json()) as { token?: string };
  return data.token ? { token: data.token, bearer } : null;
}

export function revokeSession(token: string, bearer: string): void {
  void fetch(`/api/ai/session/${encodeURIComponent(token)}`, {
    method: 'DELETE',
    headers: { Authorization: bearer },
    keepalive: true,
  }).catch(() => {});
}

export function shouldMintPreviewSession(hasAppAi: boolean, apiKey?: string, user?: User | null): boolean {
  if (!hasAppAi) return false;
  if (!user) return false;
  return Boolean(apiKey && apiKey.trim().length > 0);
}
