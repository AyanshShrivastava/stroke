import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  AudioLines,
  KeyRound,
  Loader2,
  Mic,
  MicOff,
  Send,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import type { MistUser as User } from '../types/mist';
import type { AiProviderConfig } from '../types/mist';
import type { ModelHealthIncident } from '../utils/aiErrors';
import { MistMark } from './MistLogo';

interface VoiceTurn {
  id: string;
  role: 'user' | 'assistant';
  text: string;
}

interface VoiceChatModalProps {
  isOpen: boolean;
  user: User | null;
  mode: 'create' | 'refine';
  projectName?: string;
  providerConfig: AiProviderConfig;
  onClose: () => void;
  onApplyPrompt: (synthesizedPrompt: string) => void;
  onOpenProviders: () => void;
  onIncident?: (incident: ModelHealthIncident) => void;
}

interface SpeechRecognitionInstance extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

export default function VoiceChatModal({
  isOpen,
  user,
  mode,
  projectName,
  providerConfig,
  onClose,
  onApplyPrompt,
  onOpenProviders,
  onIncident,
}: VoiceChatModalProps) {
  const [turns, setTurns] = useState<VoiceTurn[]>([]);
  const [textDraft, setTextDraft] = useState('');
  const [interimTranscript, setInterimTranscript] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(true);
  const [incident, setIncident] = useState<ModelHealthIncident | null>(null);
  const [speechSupported, setSpeechSupported] = useState(true);
  const [voiceNote, setVoiceNote] = useState('');

  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);
  const turnsRef = useRef<VoiceTurn[]>(turns);
  turnsRef.current = turns;

  const hasByokKey = Boolean(providerConfig.apiKey?.trim());
  const providerDisplay = providerConfig.name?.trim() || 'BYOK Provider';

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns, interimTranscript]);

  const stopSpeechAndMic = useCallback(() => {
    try {
      recognitionRef.current?.stop();
    } catch {
      // ignore
    }
    recognitionRef.current = null;
    setIsListening(false);
    setInterimTranscript('');
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
  }, []);

  useEffect(() => {
    if (!isOpen) {
      stopSpeechAndMic();
      return;
    }

    const SpeechRecCtor =
      typeof window !== 'undefined'
        ? ((window as unknown as Record<string, unknown>).SpeechRecognition ||
            (window as unknown as Record<string, unknown>).webkitSpeechRecognition)
        : undefined;
    setSpeechSupported(Boolean(SpeechRecCtor));
    setIncident(null);
    setInterimTranscript('');
    setVoiceNote('');
    setTurns([
      {
        id: `intro-${Date.now()}`,
        role: 'assistant',
        text:
          mode === 'refine' && projectName
            ? `Tell me what you'd like to change in ${projectName} — colors, layout, game mechanics, or new features.`
            : 'Describe the website, dashboard, or 2D/3D game you want to build and we will shape the prompt together.',
      },
    ]);

    return () => {
      stopSpeechAndMic();
    };
  }, [isOpen, mode, projectName, stopSpeechAndMic]);

  const speakText = useCallback(
    (text: string) => {
      if (!speakReplies || typeof window === 'undefined' || !('speechSynthesis' in window)) return;
      try {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.04;
        window.speechSynthesis.speak(utterance);
      } catch {
        // ignore speech synthesis errors
      }
    },
    [speakReplies],
  );

  const sendTurnToByok = useCallback(
    async (userMessage: string) => {
      const cleaned = userMessage.trim();
      if (!cleaned) return;

      const userTurn: VoiceTurn = {
        id: `user-${Date.now()}`,
        role: 'user',
        text: cleaned,
      };
      const nextHistory = [...turnsRef.current, userTurn];
      setTurns(nextHistory);
      setIncident(null);

      if (!user) {
        setVoiceNote('Sign in to Mist to receive live AI suggestions, or apply your voice note directly below.');
        return;
      }

      if (!providerConfig.apiKey?.trim()) {
        setVoiceNote('Add your BYOK API key to receive spoken AI suggestions, or build directly from your voice note below.');
        return;
      }

      setIsThinking(true);
      try {
        const idToken = await user.getIdToken();
        const resp = await fetch('/api/ai/voice-turn', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${idToken}`,
          },
          body: JSON.stringify({
            messages: nextHistory.map((t) => ({ role: t.role, content: t.text })),
            mode,
            projectName,
            providerConfig,
          }),
        });
        const data = (await resp.json()) as {
          text?: string;
          error?: string;
          incident?: ModelHealthIncident;
        };
        if (!resp.ok || !data.text) {
          if (data.incident) {
            setIncident(data.incident);
            onIncident?.(data.incident);
          }
          setVoiceNote(data.incident?.message || data.error || 'Voice response failed.');
          return;
        }
        const assistantTurn: VoiceTurn = {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          text: data.text,
        };
        setTurns((prev) => [...prev, assistantTurn]);
        speakText(data.text);
      } catch (err) {
        setVoiceNote(err instanceof Error ? err.message : 'Unable to reach BYOK voice endpoint.');
      } finally {
        setIsThinking(false);
      }
    },
    [user, mode, projectName, providerConfig, onIncident, speakText],
  );

  const toggleMicrophone = () => {
    if (isListening) {
      try {
        recognitionRef.current?.stop();
      } catch {
        // ignore
      }
      setIsListening(false);
      return;
    }

    const SpeechRecCtor = (
      (window as unknown as Record<string, unknown>).SpeechRecognition ||
      (window as unknown as Record<string, unknown>).webkitSpeechRecognition
    ) as (new () => SpeechRecognitionInstance) | undefined;

    if (!SpeechRecCtor) {
      setSpeechSupported(false);
      setVoiceNote('Browser voice recognition unavailable. Type your message below.');
      return;
    }

    try {
      const rec = new SpeechRecCtor();
      rec.continuous = false;
      rec.interimResults = true;
      rec.lang = 'en-US';
      let capturedFinal = '';

      rec.onresult = (event) => {
        let interim = '';
        let finals = '';
        for (let i = 0; i < event.results.length; i++) {
          const item = event.results[i];
          const txt = item[0]?.transcript || '';
          if (item.isFinal) finals += txt;
          else interim += txt;
        }
        if (finals) capturedFinal = finals;
        setInterimTranscript(interim || finals);
      };

      rec.onerror = (ev) => {
        setIsListening(false);
        setInterimTranscript('');
        if (ev.error === 'not-allowed') {
          setVoiceNote('Microphone access blocked. Allow microphone permissions or type below.');
        } else if (ev.error !== 'aborted') {
          setVoiceNote(`Voice capture note: ${ev.error}. You can also type below.`);
        }
      };

      rec.onend = () => {
        setIsListening(false);
        setInterimTranscript('');
        if (capturedFinal.trim()) {
          void sendTurnToByok(capturedFinal);
        }
      };

      recognitionRef.current = rec;
      setVoiceNote('');
      setIsListening(true);
      rec.start();
    } catch {
      setIsListening(false);
      setVoiceNote('Could not start microphone in this browser.');
    }
  };

  const handleSendText = (e: React.FormEvent) => {
    e.preventDefault();
    const cleaned = textDraft.trim();
    if (!cleaned || isThinking) return;
    setTextDraft('');
    void sendTurnToByok(cleaned);
  };

  const userMessages = turns.filter((t) => t.role === 'user').map((t) => t.text.trim()).filter(Boolean);
  const canApply = userMessages.length > 0;

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-labelledby="voice-modal-title"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 p-0 sm:p-4 backdrop-blur-sm"
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 18 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 14 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="flex w-full sm:max-w-xl max-h-[92dvh] flex-col overflow-hidden rounded-t-3xl sm:rounded-2xl border border-zinc-200 bg-white pb-3 sm:pb-0 shadow-2xl dark:border-zinc-800 dark:bg-zinc-950"
          >
            <div className="sm:hidden mx-auto mt-2.5 h-1 w-10 rounded-full bg-zinc-300 dark:bg-zinc-700" />
            {/* Header */}
            <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-4 dark:border-zinc-800/90">
              <div className="flex items-center gap-3 min-w-0">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl mist-primary-gradient text-white shadow-sm">
                  <AudioLines className="h-4 w-4" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <h2 id="voice-modal-title" className="font-display text-sm font-semibold text-zinc-950 dark:text-white truncate">
                    Mist Voice Studio
                  </h2>
                  <p className="text-[11px] text-zinc-500 dark:text-zinc-400 truncate">
                    {providerDisplay} · {providerConfig.model}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => {
                    const next = !speakReplies;
                    setSpeakReplies(next);
                    if (!next && 'speechSynthesis' in window) window.speechSynthesis.cancel();
                  }}
                  aria-label={speakReplies ? 'Mute voice playback' : 'Enable voice playback'}
                  className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-900 dark:hover:text-white transition-colors cursor-pointer"
                >
                  {speakReplies ? (
                    <Volume2 className="h-4 w-4 text-blue-500" aria-hidden="true" />
                  ) : (
                    <VolumeX className="h-4 w-4" aria-hidden="true" />
                  )}
                </button>
                <button
                  type="button"
                  aria-label="Close voice studio"
                  onClick={onClose}
                  className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-900 dark:hover:text-white transition-colors cursor-pointer"
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
            </div>

            {!hasByokKey && (
              <div className="mx-5 mt-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 rounded-xl border border-blue-200 bg-blue-50/90 p-3 text-xs text-blue-950 dark:border-blue-800/60 dark:bg-blue-950/35 dark:text-blue-200">
                <div className="flex items-start gap-2">
                  <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-blue-600 dark:text-blue-400" aria-hidden="true" />
                  <span>Add your BYOK API key to talk interactively with {providerDisplay}.</span>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    onOpenProviders();
                  }}
                  className="self-start sm:self-center rounded-lg bg-blue-600 px-3 py-1.5 text-[11px] font-medium text-white hover:bg-blue-700 whitespace-nowrap shrink-0 cursor-pointer"
                >
                  Add BYOK Key
                </button>
              </div>
            )}

            {incident && (
              <div
                role="alert"
                className="mx-5 mt-3 flex items-start gap-2.5 rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950 dark:border-amber-800/70 dark:bg-amber-950/40 dark:text-amber-200"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">{incident.title}</p>
                  <p className="mt-0.5 text-[11px] opacity-90">{incident.message}</p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    onOpenProviders();
                  }}
                  className="rounded-lg border border-amber-400/60 bg-white/80 px-2.5 py-1 text-[11px] font-medium text-amber-950 dark:bg-amber-900/50 dark:text-amber-100 whitespace-nowrap cursor-pointer"
                >
                  Switch Model
                </button>
              </div>
            )}

            {/* Voice Capture Bar */}
            <div className="mx-5 mt-4 flex items-center justify-between gap-4 rounded-xl border border-zinc-200 bg-gradient-to-r from-zinc-50 via-violet-50/40 to-pink-50/40 px-4 py-3 dark:border-zinc-800 dark:from-zinc-900/80 dark:via-blue-950/20 dark:to-indigo-950/20">
              <div className="flex items-center gap-2 min-w-0">
                <div className="flex items-center gap-1 h-7" aria-hidden="true">
                  {[0.4, 0.75, 1, 0.85, 0.55].map((w, i) => (
                    <span
                      key={i}
                      style={{ height: isListening ? `${Math.round(8 + 18 * w)}px` : '6px' }}
                      className={`w-1 rounded-full transition-all duration-150 ${
                        isListening ? 'bg-blue-500 animate-pulse' : 'bg-zinc-300 dark:bg-zinc-700'
                      }`}
                    />
                  ))}
                </div>
                <span className="text-xs font-medium text-zinc-700 dark:text-zinc-200 truncate">
                  {isListening
                    ? interimTranscript || 'Listening — speak your idea...'
                    : isThinking
                      ? 'Mist is thinking...'
                      : speechSupported
                        ? 'Tap Mic to speak or type below'
                        : 'Type below to plan with Mist'}
                </span>
              </div>

              {speechSupported && (
                <button
                  type="button"
                  onClick={toggleMicrophone}
                  className={`inline-flex min-h-[38px] items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-xs font-medium transition-all shrink-0 cursor-pointer ${
                    isListening
                      ? 'bg-red-600 text-white hover:bg-red-700 shadow-sm'
                      : 'mist-primary-gradient text-white shadow-sm'
                  }`}
                >
                  {isListening ? (
                    <>
                      <MicOff className="h-3.5 w-3.5" aria-hidden="true" />
                      <span>Stop</span>
                    </>
                  ) : (
                    <>
                      <Mic className="h-3.5 w-3.5" aria-hidden="true" />
                      <span>Speak</span>
                    </>
                  )}
                </button>
              )}
            </div>

            {voiceNote && (
              <p className="mx-5 mt-2 text-[11px] text-amber-700 dark:text-amber-300">{voiceNote}</p>
            )}

            {/* Transcript Feed */}
            <div className="mx-5 mt-3 h-56 overflow-y-auto rounded-xl border border-zinc-200 bg-white p-3.5 space-y-2.5 text-xs dark:border-zinc-800 dark:bg-zinc-900/40 mist-scrollbar">
              {turns.map((turn) => (
                <div
                  key={turn.id}
                  className={`rounded-xl px-3 py-2.5 leading-relaxed ${
                    turn.role === 'user'
                      ? 'ml-8 bg-gradient-to-br from-blue-600/12 to-pink-600/12 text-zinc-950 dark:text-zinc-100'
                      : 'mr-8 border border-zinc-200 bg-zinc-50 text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200'
                  }`}
                >
                  <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                    {turn.role === 'user' ? 'You' : 'Mist'}
                  </p>
                  <p>{turn.text}</p>
                </div>
              ))}
              {isThinking && (
                <div className="mr-8 inline-flex items-center gap-2 rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" aria-hidden="true" />
                  <span>Thinking with {providerConfig.model}...</span>
                </div>
              )}
              <div ref={transcriptEndRef} />
            </div>

            {/* Text Input + Build CTA */}
            <div className="p-5 space-y-3">
              <form onSubmit={handleSendText} className="flex items-center gap-2">
                <label htmlFor="voice-text-input" className="sr-only">
                  Send message in Voice Studio
                </label>
                <input
                  id="voice-text-input"
                  type="text"
                  value={textDraft}
                  onChange={(e) => setTextDraft(e.target.value)}
                  disabled={isThinking}
                  placeholder="Speak above or type what you want to build..."
                  className="flex-1 rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-950 placeholder:text-zinc-400 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100"
                />
                <button
                  type="submit"
                  disabled={isThinking || !textDraft.trim()}
                  aria-label="Send message"
                  className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-zinc-950 text-white hover:bg-zinc-800 disabled:opacity-40 dark:bg-white dark:text-zinc-950 dark:hover:bg-zinc-200 cursor-pointer"
                >
                  <Send className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </form>

              <div className="flex items-center justify-between gap-3 border-t border-zinc-200 pt-3 dark:border-zinc-800">
                <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
                  {mode === 'create'
                    ? 'Turn your conversation into a multi-file website.'
                    : 'Send your requested changes straight to the editor.'}
                </span>
                <button
                  type="button"
                  disabled={!canApply}
                  onClick={() => {
                    const summary = userMessages.join(' ');
                    if (summary) {
                      onApplyPrompt(summary);
                      onClose();
                    }
                  }}
                  className="inline-flex items-center gap-1.5 rounded-xl mist-primary-gradient px-4 py-2 text-xs font-medium text-white shadow-sm disabled:opacity-40 transition-all whitespace-nowrap shrink-0 cursor-pointer"
                >
                  <MistMark className="h-3.5 w-3.5" title="Build" />
                  <span>{mode === 'create' ? 'Build from Voice' : 'Apply to Website'}</span>
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
