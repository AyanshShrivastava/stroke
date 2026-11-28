import React, { useEffect, useState } from 'react';
import {
  Download,
  Terminal,
  ExternalLink,
  Check,
  Copy,
  X,
  Monitor,
  Apple,
  Cpu,
  Layers,
  Sparkles,
  ShieldCheck,
  RefreshCw,
  FolderGit2
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';

interface MistCodeModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface EngineHealth {
  connected: boolean;
  version?: string;
  uptime?: number;
  pid?: number;
  activeTerminals?: number;
}

export default function MistCodeModal({ isOpen, onClose }: MistCodeModalProps) {
  const [copiedCmd, setCopiedCmd] = useState(false);
  const [engineHealth, setEngineHealth] = useState<EngineHealth>({ connected: false });
  const [probing, setProbing] = useState(false);

  const probeLocalEngine = async () => {
    setProbing(true);
    try {
      const res = await fetch('http://127.0.0.1:8501/health', { method: 'GET' });
      if (res.ok) {
        const data = await res.json();
        setEngineHealth({
          connected: true,
          version: data.version || '1.0.0',
          uptime: data.uptime_seconds,
          pid: data.pid,
          activeTerminals: data.active_terminals ?? 0
        });
      } else {
        setEngineHealth({ connected: false });
      }
    } catch {
      setEngineHealth({ connected: false });
    } finally {
      setProbing(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      probeLocalEngine();
      const interval = setInterval(probeLocalEngine, 5000);
      return () => clearInterval(interval);
    }
  }, [isOpen]);

  const copyCommand = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedCmd(true);
    setTimeout(() => setCopiedCmd(false), 2000);
  };

  const handleDownload = (_platform: string, _filename: string) => {
    const releasesUrl = 'https://github.com/AyanshShrivastava/stroke/releases';
    window.open(releasesUrl, '_blank', 'noopener,noreferrer');
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="fixed inset-0 bg-black/70 backdrop-blur-md"
        />

        {/* Modal Window */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 10 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          className="relative w-full max-w-2xl overflow-hidden rounded-2xl border border-zinc-200/80 bg-white/95 p-6 shadow-2xl backdrop-blur-2xl dark:border-white/10 dark:bg-[#141417]/95 text-zinc-900 dark:text-zinc-100 flex flex-col max-h-[90vh]"
        >
          {/* Header */}
          <div className="flex items-start justify-between border-b border-zinc-200 pb-4 dark:border-white/5">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-tr from-blue-600 via-indigo-600 to-violet-600 shadow-md shadow-blue-500/20 text-white">
                <Terminal className="h-5 w-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-bold tracking-tight text-zinc-950 dark:text-white">Mist Code</h2>
                  <span className="rounded-full bg-blue-500/10 px-2 py-0.5 text-[10px] font-mono font-semibold text-blue-600 dark:text-blue-400 border border-blue-500/20">
                    Desktop Companion
                  </span>
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                  Native engineering runtime for Roblox Studio MCP, sandboxed terminal, and BYOK AI.
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-white/10 dark:hover:text-white transition-colors cursor-pointer"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="overflow-y-auto space-y-5 py-4 pr-1">
            {/* Live Engine Status Banner */}
            <div className={`rounded-xl border p-3.5 flex items-center justify-between transition-all ${
              engineHealth.connected
                ? 'border-emerald-500/30 bg-emerald-500/[0.06] dark:border-emerald-500/30 dark:bg-emerald-950/20'
                : 'border-zinc-200 bg-zinc-50/80 dark:border-white/5 dark:bg-white/[0.02]'
            }`}>
              <div className="flex items-center gap-3">
                <div className="relative flex h-3 w-3 items-center justify-center">
                  {engineHealth.connected ? (
                    <>
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                    </>
                  ) : (
                    <span className="h-2 w-2 rounded-full bg-zinc-400 dark:bg-zinc-600" />
                  )}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold">
                      {engineHealth.connected ? 'Local Engine Connected' : 'Local Engine Offline'}
                    </span>
                    {engineHealth.connected && (
                      <span className="text-[10px] font-mono text-emerald-600 dark:text-emerald-400">
                        PID: {engineHealth.pid} • 127.0.0.1:8501
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
                    {engineHealth.connected
                      ? `Active terminals: ${engineHealth.activeTerminals} • Ready for Roblox Studio MCP & local execution`
                      : 'Launch Mist Code locally or run the desktop app to enable native host features.'}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={probeLocalEngine}
                  disabled={probing}
                  className="rounded-lg border border-zinc-200 dark:border-white/10 p-1.5 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-white/10 transition cursor-pointer"
                  title="Refresh connection status"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${probing ? 'animate-spin' : ''}`} />
                </button>
                {engineHealth.connected && (
                  <button
                    type="button"
                    onClick={() => window.open('http://127.0.0.1:8501', '_blank', 'noopener,noreferrer')}
                    className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white px-2.5 py-1 text-xs font-medium transition cursor-pointer"
                  >
                    <span>Open Dashboard</span>
                    <ExternalLink className="h-3 w-3" />
                  </button>
                )}
              </div>
            </div>

            {/* Desktop Downloads Section */}
            <div>
              <div className="text-xs font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 font-mono mb-2.5">
                Download Native Application
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {/* macOS Apple Silicon */}
                <button
                  type="button"
                  onClick={() => handleDownload('mac-arm64', 'Mist-Code-AppleSilicon.dmg')}
                  className="flex flex-col items-start justify-between p-3.5 rounded-xl border border-zinc-200 bg-zinc-50/50 hover:bg-zinc-100/80 hover:border-blue-500/40 dark:border-white/10 dark:bg-white/[0.02] dark:hover:bg-white/[0.06] transition-all group cursor-pointer text-left"
                >
                  <div className="flex items-center justify-between w-full mb-2">
                    <Apple className="h-5 w-5 text-zinc-800 dark:text-zinc-200 group-hover:text-blue-500 transition-colors" />
                    <span className="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-600 dark:text-blue-400">ARM64</span>
                  </div>
                  <div>
                    <div className="text-xs font-bold group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">macOS (Apple Silicon)</div>
                    <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">M1 / M2 / M3 / M4 Macs (.dmg)</div>
                  </div>
                  <div className="mt-3 inline-flex items-center gap-1 text-[11px] font-medium text-blue-600 dark:text-blue-400 group-hover:underline">
                    <Download className="h-3 w-3" />
                    <span>Download</span>
                  </div>
                </button>

                {/* macOS Intel */}
                <button
                  type="button"
                  onClick={() => handleDownload('mac-x64', 'Mist-Code-Intel.dmg')}
                  className="flex flex-col items-start justify-between p-3.5 rounded-xl border border-zinc-200 bg-zinc-50/50 hover:bg-zinc-100/80 hover:border-blue-500/40 dark:border-white/10 dark:bg-white/[0.02] dark:hover:bg-white/[0.06] transition-all group cursor-pointer text-left"
                >
                  <div className="flex items-center justify-between w-full mb-2">
                    <Apple className="h-5 w-5 text-zinc-800 dark:text-zinc-200 group-hover:text-blue-500 transition-colors" />
                    <span className="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded bg-zinc-200/60 text-zinc-700 dark:bg-white/10 dark:text-zinc-300">x86_64</span>
                  </div>
                  <div>
                    <div className="text-xs font-bold group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">macOS (Intel)</div>
                    <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">Intel-based Mac computers (.dmg)</div>
                  </div>
                  <div className="mt-3 inline-flex items-center gap-1 text-[11px] font-medium text-blue-600 dark:text-blue-400 group-hover:underline">
                    <Download className="h-3 w-3" />
                    <span>Download</span>
                  </div>
                </button>

                {/* Windows x64 */}
                <button
                  type="button"
                  onClick={() => handleDownload('win-x64', 'Mist-Code-Setup-x64.exe')}
                  className="flex flex-col items-start justify-between p-3.5 rounded-xl border border-zinc-200 bg-zinc-50/50 hover:bg-zinc-100/80 hover:border-blue-500/40 dark:border-white/10 dark:bg-white/[0.02] dark:hover:bg-white/[0.06] transition-all group cursor-pointer text-left"
                >
                  <div className="flex items-center justify-between w-full mb-2">
                    <Monitor className="h-5 w-5 text-zinc-800 dark:text-zinc-200 group-hover:text-blue-500 transition-colors" />
                    <span className="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded bg-zinc-200/60 text-zinc-700 dark:bg-white/10 dark:text-zinc-300">Windows</span>
                  </div>
                  <div>
                    <div className="text-xs font-bold group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">Windows 10 / 11</div>
                    <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">64-bit installer & portable (.exe)</div>
                  </div>
                  <div className="mt-3 inline-flex items-center gap-1 text-[11px] font-medium text-blue-600 dark:text-blue-400 group-hover:underline">
                    <Download className="h-3 w-3" />
                    <span>Download</span>
                  </div>
                </button>
              </div>
            </div>

            {/* Quickstart via Terminal */}
            <div className="rounded-xl border border-zinc-200 bg-zinc-50/60 p-3.5 dark:border-white/10 dark:bg-black/30">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-1.5 text-xs font-semibold">
                  <Terminal className="h-3.5 w-3.5 text-blue-500" />
                  <span>Developer CLI / Run Locally</span>
                </div>
                <button
                  type="button"
                  onClick={() => copyCommand('git clone https://github.com/AyanshShrivastava/stroke.git mist-code && cd mist-code && ./venv/bin/python desktop.py')}
                  className="inline-flex items-center gap-1 text-[11px] text-zinc-500 hover:text-zinc-900 dark:hover:text-white transition cursor-pointer"
                >
                  {copiedCmd ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                  <span>{copiedCmd ? 'Copied' : 'Copy command'}</span>
                </button>
              </div>
              <div className="rounded-lg bg-zinc-900 p-2.5 font-mono text-[11px] text-zinc-300 overflow-x-auto select-all">
                git clone https://github.com/AyanshShrivastava/stroke.git mist-code && cd mist-code && ./venv/bin/python desktop.py
              </div>
            </div>

            {/* Feature Highlights Grid */}
            <div className="grid grid-cols-2 gap-2.5 pt-1 text-xs">
              <div className="flex items-start gap-2 p-2.5 rounded-lg bg-zinc-100/60 dark:bg-white/[0.02]">
                <Cpu className="h-4 w-4 text-blue-500 shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold">Roblox Studio MCP</div>
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400 leading-tight mt-0.5">Live game tree inspection and Luau code execution in active Studio sessions.</div>
                </div>
              </div>

              <div className="flex items-start gap-2 p-2.5 rounded-lg bg-zinc-100/60 dark:bg-white/[0.02]">
                <ShieldCheck className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold">Sandboxed Terminal</div>
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400 leading-tight mt-0.5">Isolated test runs, Luau compiler validation, and file diff backups.</div>
                </div>
              </div>

              <div className="flex items-start gap-2 p-2.5 rounded-lg bg-zinc-100/60 dark:bg-white/[0.02]">
                <Sparkles className="h-4 w-4 text-violet-500 shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold">BYOK AI Synthesis</div>
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400 leading-tight mt-0.5">Direct encrypted key storage for Gemini, Claude 3.7, OpenAI, Groq, and DeepSeek.</div>
                </div>
              </div>

              <div className="flex items-start gap-2 p-2.5 rounded-lg bg-zinc-100/60 dark:bg-white/[0.02]">
                <FolderGit2 className="h-4 w-4 text-pink-500 shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold">Clerk SSO Unified Auth</div>
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400 leading-tight mt-0.5">Share your Mist credentials automatically with your desktop workspace.</div>
                </div>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-zinc-200 pt-3 dark:border-white/5 text-xs text-zinc-500">
            <span>Open Source • Apache-2.0 / MIT</span>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-4 py-1.5 text-xs font-semibold text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-white/10 transition cursor-pointer"
            >
              Close
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
