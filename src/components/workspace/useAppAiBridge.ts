import { useEffect, useRef } from 'react';
import type { MistUser as User, AiProviderConfig, SelectedVisualElement, VisualElementPatch } from '../../types/mist';
import { relayAppAiRequest } from './appAiRelay';
import { useEphemeralPreviewSession } from './useEphemeralPreviewSession';

export function isValidSelectedElement(p: unknown): p is SelectedVisualElement {
  if (!p || typeof p !== 'object') return false;
  const el = p as Partial<SelectedVisualElement>;
  return (
    typeof el.mistId === 'string' &&
    typeof el.tagName === 'string' &&
    typeof el.textContent === 'string' &&
    typeof el.className === 'string' &&
    Boolean(el.styles && typeof el.styles === 'object')
  );
}

interface UseAppAiBridgeParams {
  hasAppAi: boolean;
  providerConfig: AiProviderConfig;
  user: User | null;
  viewMode: string;
  onSelectElement: (el: SelectedVisualElement) => void;
}

function isIframeMessage(event: MessageEvent, targetWindow: Window | null): boolean {
  if (!targetWindow) return false;
  if (event.source !== targetWindow) return false;
  return Boolean(event.data && typeof event.data === 'object');
}

interface MessageContext {
  onSelectElement: (el: SelectedVisualElement) => void;
  user: User | null;
  hasAppAi: boolean;
  providerConfig: AiProviderConfig;
  sessionToken: string | null;
}

function handleIncomingMessage(data: unknown, win: Window, ctx: MessageContext): void {
  const msg = data as { type?: unknown; requestId?: unknown; payload?: unknown };

  if (msg.type === 'MIST_SELECT_ELEMENT' && isValidSelectedElement(msg.payload)) {
    ctx.onSelectElement(msg.payload);
    return;
  }

  if (msg.type === 'MIST_APP_AI_REQUEST' && typeof msg.requestId === 'string') {
    const payload = msg.payload && typeof msg.payload === 'object'
      ? (msg.payload as Record<string, unknown>)
      : {};
    void relayAppAiRequest({
      reqId: msg.requestId,
      payload,
      user: ctx.user,
      hasAppAi: ctx.hasAppAi,
      providerConfig: ctx.providerConfig,
      sessionToken: ctx.sessionToken,
      targetWindow: win,
    });
  }
}

export function useAppAiBridge({
  hasAppAi,
  providerConfig,
  user,
  viewMode,
  onSelectElement,
}: UseAppAiBridgeParams) {
  const sessionToken = useEphemeralPreviewSession(hasAppAi, providerConfig, user);
  const sessionTokenRef = useRef<string | null>(null);
  sessionTokenRef.current = sessionToken;
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const win = iframeRef.current?.contentWindow || null;
      if (!isIframeMessage(event, win) || !win) return;
      handleIncomingMessage(event.data, win, {
        onSelectElement,
        user,
        hasAppAi,
        providerConfig,
        sessionToken: sessionTokenRef.current,
      });
    };

    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [hasAppAi, onSelectElement, providerConfig, user]);

  const syncBridgeToIframe = () => {
    const win = iframeRef.current?.contentWindow;
    if (win) {
      win.postMessage({ type: 'MIST_TOGGLE_INSPECTOR', enabled: viewMode === 'visual' }, '*');
      win.postMessage({ type: 'MIST_SET_APP_AI_STATE', payload: { appAiEnabled: hasAppAi } }, '*');
    }
  };

  const handleLivePreviewPatch = (patch: VisualElementPatch) => {
    const win = iframeRef.current?.contentWindow;
    if (win) {
      win.postMessage({ type: 'MIST_LIVE_PATCH', payload: patch }, '*');
    }
  };

  return {
    iframeRef,
    sessionToken,
    syncBridgeToIframe,
    handleLivePreviewPatch,
  };
}
