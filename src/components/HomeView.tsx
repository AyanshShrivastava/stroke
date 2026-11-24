import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  Box,
  CheckCircle2,
  ChevronDown,
  Code2,
  Copy,
  Cpu,
  Download,
  FileCode2,
  FolderOpen,
  Gamepad2,
  Globe,
  KeyRound,
  Layers,
  Loader2,
  Menu,
  Mic,
  Moon,
  Pause,
  Play,
  Search,
  Settings,
  Sun,
  Terminal,
  Trash2,
  User as UserIcon,
  X,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import type { MistUser as User } from '../types/mist';
import type {
  AiProviderConfig,
  AiStreamProgress,
  AppAiMode,
  CatalogSource,
  DeploymentRecord,
  MistProject,
  WebSearchMode,
} from '../types/mist';
import type { ModelHealthIncident } from '../utils/aiErrors';
import {
  CUSTOM_GATEWAY_PRESETS,
  detectGatewayFromBaseUrl,
  fetchLiveModelCatalog,
  findModelEntry,
  shouldEnableAppAi,
  type CustomGatewayId,
  type ModelCatalogItem,
} from '../data/models';
import MistLogo, { MistMark } from './MistLogo';
import ModelSelectorDropdown from './ModelSelectorDropdown';
import { maskApiKey } from '../utils/projectOps';
import showcasePromptImg from '../assets/images/mist_showcase_prompt_1794824266440.jpg';
import showcaseBuildImg from '../assets/images/mist_showcase_build_1794824267456.jpg';
import showcaseLaunchImg from '../assets/images/mist_showcase_launch_1794824268004.jpg';
import templateCoffeeImg from '../assets/images/template_coffee_roastery_1794659272127.jpg';
import templateAudioImg from '../assets/images/template_audio_hardware_1794659272890.jpg';
import templateArchitectImg from '../assets/images/template_architect_studio_1794659273332.jpg';
import templateSkincareImg from '../assets/images/template_botanical_skincare_1794659273501.jpg';

interface HomeViewProps {
  user: User | null;
  projects: MistProject[];
  deployments: DeploymentRecord[];
  providerConfig: AiProviderConfig;
  modelIncident: ModelHealthIncident | null;
  isGenerating: boolean;
  streamProgress: AiStreamProgress | null;
  generationError: string | null;
  darkMode: boolean;
  appAiMode: AppAiMode;
  webSearchMode: WebSearchMode;
  hasWebSearchKey: boolean;
  onChangeAppAiMode: (mode: AppAiMode) => void;
  onChangeWebSearchMode: (mode: WebSearchMode) => void;
  onToggleDarkMode: () => void;
  onSaveProvider: (next: AiProviderConfig) => void;
  onGenerate: (prompt: string) => void;
  onCancelGeneration: () => void;
  onOpenVoiceChat: () => void;
  onOpenProject: (project: MistProject) => void;
  onPublishProject: (project: MistProject) => void;
  onDuplicateProject: (project: MistProject) => void;
  onDeleteProject: (projectId: string) => void;
  onOpenProviders: () => void;
  onOpenSettings: () => void;
  onOpenDeployments: () => void;
  onOpenAccount: () => void;
  onOpenMistCode?: () => void;
}

const INTERACTIVE_MODES = [
  {
    id: 'web',
    label: 'Web App',
    detail: 'Landing pages, SaaS tools & dashboards',
    icon: Layers,
    starterPrompt:
      'Minimalist Tokyo specialty coffee roastery website with single-origin menu, brew ratio calculator, and bar reservation.',
  },
  {
    id: 'game',
    label: '2D Canvas Game',
    detail: 'Playable arcade runners & physics games',
    icon: Gamepad2,
    starterPrompt:
      'Interactive Subway Surfers 2D endless runner game on an HTML5 canvas with 3 train lanes, coin pickups, oncoming barriers, keyboard & swipe controls, and Play/Restart buttons.',
  },
  {
    id: '3d',
    label: '3D Scene',
    detail: 'Three.js interactive product & spatial views',
    icon: Box,
    starterPrompt:
      'Interactive Three.js 3D architectural product studio with OrbitControls, real-time PBR materials, camera angle presets, and clean HUD overlay.',
  },
  {
    id: 'research',
    label: 'Live Web App',
    detail: 'Real web research with verified source links',
    icon: Globe,
    starterPrompt:
      'Editorial AI research digest & writing workspace with live web search citations and an in-app assistant powered by POST /api/app-ai.',
  },
] as const;

const WORKFLOW_STEPS = [
  {
    step: '01',
    title: 'Give a Simple Prompt',
    caption: 'Describe your idea in plain English or use Voice Studio.',
    image: showcasePromptImg,
    alt: 'Studio desk showing a prompt composer turning an idea into a web layout plan',
    samplePrompt: '"Build a Tokyo specialty coffee roastery site with a brew ratio calculator."',
    sampleFiles: ['Prompt queued', 'Model ready (BYOK)'],
    outcome: 'Understands layout, interactivity, 2D Canvas, or 3D scene requirements automatically.',
  },
  {
    step: '02',
    title: 'AI Builds & Researches Live',
    caption: 'Generates complete React + TypeScript files and verifies real web sources.',
    image: showcaseBuildImg,
    alt: 'Widescreen monitor displaying React TypeScript code beside a live website preview',
    samplePrompt: 'Writing src/App.tsx, src/components/BrewCalculator.tsx, src/index.css...',
    sampleFiles: ['src/App.tsx', 'src/components/Menu.tsx', 'src/index.css'],
    outcome: 'Edit visually by clicking elements or chatting in AI Refine with Chat & Preview tabs.',
  },
  {
    step: '03',
    title: 'Download ZIP & Host Free',
    caption: 'Clicking Publish downloads your standalone site ready for no-card free hosts.',
    image: showcaseLaunchImg,
    alt: 'Minimalist laptop displaying the finished specialty coffee roastery website live in browser',
    samplePrompt: 'Packaged dist/index.html + render.yaml -> Ready for Netlify Drop or Render Static.',
    sampleFiles: ['dist/index.html', 'render.yaml', 'DEPLOY_FREE.md'],
    outcome: '100% standalone static output — zero visitor load on Mist’s server.',
  },
] as const;

export default function HomeView({
  user,
  projects,
  deployments,
  providerConfig,
  modelIncident,
  isGenerating,
  streamProgress,
  generationError,
  darkMode,
  appAiMode,
  webSearchMode,
  hasWebSearchKey,
  onChangeAppAiMode,
  onChangeWebSearchMode,
  onToggleDarkMode,
  onSaveProvider,
  onGenerate,
  onCancelGeneration,
  onOpenVoiceChat,
  onOpenProject,
  onPublishProject,
  onDuplicateProject,
  onDeleteProject,
  onOpenProviders,
  onOpenSettings,
  onOpenDeployments,
  onOpenAccount,
  onOpenMistCode,
}: HomeViewProps) {
  const [promptInput, setPromptInput] = useState('');
  const [selectedMode, setSelectedMode] = useState<string>('web');
  const [promptValidationError, setPromptValidationError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [projectFilter, setProjectFilter] = useState<'all' | 'published' | 'draft'>('all');
  const [quickModelOpen, setQuickModelOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  // Interactive Prompt-to-Website Walkthrough state
  const [activeShowcaseStep, setActiveShowcaseStep] = useState(0);
  const [isShowcasePlaying, setIsShowcasePlaying] = useState(() => {
    if (typeof window !== 'undefined' && window.matchMedia) {
      return !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }
    return true;
  });
  const [showLoggedInTour, setShowLoggedInTour] = useState(false);

  const [liveModels, setLiveModels] = useState<ModelCatalogItem[] | null>(null);
  const [catalogSource, setCatalogSource] = useState<CatalogSource>('preset');
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);
  const [isOutdatedFallback, setIsOutdatedFallback] = useState(false);
  const [isLoadingCatalog, setIsLoadingCatalog] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [catalogNote, setCatalogNote] = useState<string | undefined>(undefined);
  const promptInputRef = useRef<HTMLTextAreaElement | null>(null);
  const catalogAbortRef = useRef<AbortController | null>(null);
  const catalogSeqRef = useRef(0);

  useEffect(() => {
    if (!isShowcasePlaying) return;
    if (user && !showLoggedInTour) return;
    const id = window.setInterval(() => {
      setActiveShowcaseStep((prev) => (prev + 1) % WORKFLOW_STEPS.length);
    }, 4500);
    return () => window.clearInterval(id);
  }, [isShowcasePlaying, user, showLoggedInTour]);

  const loadQuickCatalog = useCallback(
    async (forceRefresh = false) => {
      catalogAbortRef.current?.abort();
      const seq = ++catalogSeqRef.current;

      const cleanUrl = (providerConfig.baseUrl || '').trim();
      if (!cleanUrl) {
        setLiveModels(null);
        setCatalogSource('preset');
        setLastRefreshedAt(null);
        setIsOutdatedFallback(false);
        setCatalogError(null);
        setIsLoadingCatalog(false);
        setCatalogNote('Enter a custom endpoint URL in Models & Keys to fetch models.');
        return;
      }

      const controller = new AbortController();
      catalogAbortRef.current = controller;
      setIsLoadingCatalog(true);
      setCatalogError(null);

      try {
        const idToken = user ? (await user.getIdToken()) ?? undefined : undefined;
        if (seq !== catalogSeqRef.current || controller.signal.aborted) return;
        const res = await fetchLiveModelCatalog({
          baseUrl: cleanUrl,
          apiKey: providerConfig.apiKey,
          forceRefresh,
          idToken,
          signal: controller.signal,
        });
        if (seq !== catalogSeqRef.current || controller.signal.aborted) return;
        setLiveModels(res.models);
        setCatalogSource(res.source);
        setLastRefreshedAt(res.fetchedAt);
        setIsOutdatedFallback(Boolean(res.isOutdatedFallback));
        setCatalogNote(res.note);
      } catch (err) {
        if (seq !== catalogSeqRef.current || controller.signal.aborted) return;
        setCatalogSource('preset');
        setIsOutdatedFallback(true);
        setCatalogError(err instanceof Error ? err.message : 'Unable to refresh catalog.');
      } finally {
        if (seq === catalogSeqRef.current) {
          setIsLoadingCatalog(false);
        }
      }
    },
    [providerConfig.baseUrl, providerConfig.apiKey, user],
  );

  useEffect(() => {
    if (!quickModelOpen) {
      catalogAbortRef.current?.abort();
      return;
    }
    void loadQuickCatalog(false);
    return () => {
      catalogAbortRef.current?.abort();
    };
  }, [quickModelOpen, loadQuickCatalog]);

  useEffect(() => {
    if (!isGenerating || !streamProgress) {
      setElapsedSeconds(0);
      return;
    }
    const update = () => {
      setElapsedSeconds(Math.max(1, Math.floor((Date.now() - streamProgress.startedAt) / 1000)));
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [isGenerating, streamProgress]);

  const filteredProjects = useMemo(() => {
    return projects.filter((proj) => {
      const matchesFilter =
        projectFilter === 'all' ||
        (projectFilter === 'published' && proj.isPublished) ||
        (projectFilter === 'draft' && !proj.isPublished);
      const q = searchQuery.trim().toLowerCase();
      const matchesQuery =
        !q ||
        proj.name.toLowerCase().includes(q) ||
        proj.description.toLowerCase().includes(q) ||
        proj.prompt.toLowerCase().includes(q);
      return matchesFilter && matchesQuery;
    });
  }, [projects, projectFilter, searchQuery]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!promptInput.trim()) {
      setPromptValidationError('Describe the website you want Mist to build before generating.');
      return;
    }
    setPromptValidationError(null);
    onGenerate(promptInput.trim());
  };

  const activeGatewayId: CustomGatewayId = detectGatewayFromBaseUrl(providerConfig.baseUrl);
  const activeGateway =
    CUSTOM_GATEWAY_PRESETS.find((g) => g.id === activeGatewayId) || CUSTOM_GATEWAY_PRESETS[0];
  const currentModelMeta = findModelEntry(
    providerConfig.provider,
    providerConfig.model,
    providerConfig.baseUrl,
    liveModels || undefined,
  );
  const providerDisplayName = providerConfig.name?.trim() || activeGateway.name;
  const hasApiKey = Boolean(providerConfig.apiKey?.trim());
  const providerLabel = `${providerDisplayName} · ${
    providerConfig.model ? currentModelMeta?.label || providerConfig.model : 'Select model'
  }`;
  const appAiActiveForPrompt = shouldEnableAppAi(promptInput, appAiMode);
  const currentStepData = WORKFLOW_STEPS[activeShowcaseStep] || WORKFLOW_STEPS[0];

  const renderShowcaseWalkthrough = () => (
    <section
      id="walkthrough"
      aria-label="How Mist builds websites"
      className="mx-auto max-w-6xl px-4 sm:px-6 pb-12"
    >
      <div className="rounded-2xl border border-zinc-200/90 bg-white/85 p-4 sm:p-6 dark:border-zinc-800/90 dark:bg-zinc-950/75">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
          <div>
            <h2 className="font-display text-lg sm:text-xl font-semibold tracking-tight text-zinc-950 dark:text-white">
              From Prompt to Free Live Website
            </h2>
            <p className="mt-0.5 text-xs sm:text-sm text-zinc-600 dark:text-zinc-400">
              Watch how Mist turns plain-English prompts into standalone React code ready for free static hosting.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIsShowcasePlaying((p) => !p)}
              className="inline-flex min-h-[34px] items-center gap-1.5 rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 cursor-pointer whitespace-nowrap"
            >
              {isShowcasePlaying ? (
                <>
                  <Pause className="h-3.5 w-3.5 text-blue-500" aria-hidden="true" />
                  <span>Pause Reel</span>
                </>
              ) : (
                <>
                  <Play className="h-3.5 w-3.5 text-blue-500" aria-hidden="true" />
                  <span>Play Reel</span>
                </>
              )}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-stretch">
          {/* Interactive Step Selector */}
          <div className="lg:col-span-5 flex flex-col justify-between gap-2.5">
            {WORKFLOW_STEPS.map((item, idx) => {
              const isActive = idx === activeShowcaseStep;
              return (
                <button
                  key={item.step}
                  type="button"
                  onClick={() => {
                    setActiveShowcaseStep(idx);
                    setIsShowcasePlaying(false);
                  }}
                  className={`flex-1 rounded-xl border p-3.5 text-left transition-colors cursor-pointer ${
                    isActive
                      ? 'border-blue-500/80 bg-blue-50/75 dark:border-blue-500/70 dark:bg-blue-950/30'
                      : 'border-zinc-200/80 bg-zinc-50/60 hover:bg-zinc-100/70 dark:border-zinc-800/80 dark:bg-zinc-900/50 dark:hover:bg-zinc-900'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-display text-sm font-semibold text-zinc-950 dark:text-white">
                      {item.step}. {item.title}
                    </span>
                    {isActive && (
                      <span className="text-[11px] font-medium text-blue-600 dark:text-blue-400">
                        Viewing
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed">
                    {item.caption}
                  </p>
                </button>
              );
            })}
          </div>

          {/* Synchronized Visual Frame */}
          <div className="lg:col-span-7 relative overflow-hidden rounded-xl border border-zinc-200 bg-zinc-950 dark:border-zinc-800 lg:min-h-[340px] flex flex-col justify-end">
            <div className="relative h-48 sm:h-56 lg:absolute lg:inset-0 lg:h-full w-full overflow-hidden">
              <img
                src={currentStepData.image}
                alt={currentStepData.alt}
                referrerPolicy="no-referrer"
                className="h-full w-full object-cover object-center transition-opacity duration-300"
              />
              <div
                aria-hidden="true"
                className="hidden lg:block absolute inset-0 bg-gradient-to-t from-black/90 via-black/45 to-black/15"
              />
            </div>
            <div className="relative z-10 bg-zinc-950 lg:bg-transparent p-4 sm:p-5 text-white space-y-2">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-zinc-300 font-mono">
                <span>Step {currentStepData.step} of 03</span>
                <span aria-hidden="true">·</span>
                <span>{currentStepData.sampleFiles.join(' · ')}</span>
              </div>
              <p className="font-mono text-xs sm:text-sm text-zinc-100 bg-black/55 border border-white/15 rounded-lg px-3 py-2">
                {currentStepData.samplePrompt}
              </p>
              <p className="text-xs text-zinc-300 lg:text-zinc-200 leading-relaxed">
                {currentStepData.outcome}
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );

  // ---- Rotating example prompts for the composer placeholder ----
  const placeholderIdeas = useMemo(
    () => [
      'a Tokyo coffee roastery site with a brew calculator…',
      'a neon 2D runner game with high scores…',
      'a 3D product viewer for wireless headphones…',
      'a portfolio for a landscape photographer…',
      'a SaaS dashboard for tracking habits…',
    ],
    [],
  );
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const [placeholderChars, setPlaceholderChars] = useState(0);
  useEffect(() => {
    if (promptInput) return;
    const full = placeholderIdeas[placeholderIndex];
    const done = placeholderChars >= full.length;
    const t = window.setTimeout(
      () => {
        if (done) {
          setPlaceholderChars(0);
          setPlaceholderIndex((i) => (i + 1) % placeholderIdeas.length);
        } else {
          setPlaceholderChars((c) => c + 1);
        }
      },
      done ? 1800 : 38,
    );
    return () => window.clearTimeout(t);
  }, [placeholderChars, placeholderIndex, placeholderIdeas, promptInput]);
  const animatedPlaceholder = `Ask Mist to build ${placeholderIdeas[placeholderIndex].slice(0, placeholderChars)}`;

  const projectSearchRef = useRef<HTMLInputElement | null>(null);
  const firstName = user ? user.displayName?.split(' ')[0] || user.email?.split('@')[0] || 'there' : '';

  const focusComposer = (prompt?: string) => {
    if (prompt !== undefined) {
      setPromptInput(prompt);
      setPromptValidationError(null);
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
    window.setTimeout(() => promptInputRef.current?.focus(), 250);
  };

  const themeButton = (
    <button
      type="button"
      onClick={onToggleDarkMode}
      aria-label={darkMode ? 'Switch to light theme' : 'Switch to dark theme'}
      className="inline-flex h-9 w-9 items-center justify-center rounded-full text-zinc-600 hover:bg-zinc-900/5 hover:text-zinc-950 dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:text-white transition-colors cursor-pointer"
    >
      {darkMode ? <Sun className="h-4 w-4" aria-hidden="true" /> : <Moon className="h-4 w-4" aria-hidden="true" />}
    </button>
  );

  const composerBlock = (
    <>
          {/* Interactive One-Tap Builder Type Picker */}
          <div className="mt-8 grid grid-cols-2 lg:grid-cols-4 gap-2.5">
            {INTERACTIVE_MODES.map((mode) => {
              const Icon = mode.icon;
              const isSelected = selectedMode === mode.id;
              return (
                <button
                  key={mode.id}
                  type="button"
                  onClick={() => {
                    setSelectedMode(mode.id);
                    setPromptInput(mode.starterPrompt);
                    setPromptValidationError(null);
                    if (mode.id === 'research') {
                      onChangeWebSearchMode('on');
                      onChangeAppAiMode('always');
                    }
                    promptInputRef.current?.focus();
                  }}
                  className={`mist-mode-card flex min-h-[88px] flex-col items-start justify-between gap-2 rounded-2xl border p-3.5 text-left transition-all duration-200 cursor-pointer ${
                    isSelected
                      ? 'mist-gradient-border shadow-lg shadow-violet-500/10'
                      : 'border-zinc-200/75 hover:border-zinc-300 hover:-translate-y-0.5 dark:border-zinc-800/85 dark:hover:border-zinc-700'
                  }`}
                >
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-zinc-950 dark:text-white">
                    <Icon className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400 shrink-0" aria-hidden="true" />
                    <span>{mode.label}</span>
                  </span>
                  <span className="text-[11px] text-zinc-600 dark:text-zinc-400 leading-snug">
                    {mode.detail}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Model Health Warning Banner */}
          <AnimatePresence>
            {modelIncident && (
              <motion.div
                role="alert"
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                className="mt-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-amber-300 bg-amber-50/95 px-4 py-3 text-xs text-amber-950 dark:border-amber-700/60 dark:bg-amber-950/50 dark:text-amber-200"
              >
                <div className="flex items-start gap-2.5">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
                  <div>
                    <p className="font-semibold">{modelIncident.title}</p>
                    <p className="mt-0.5 text-[11px] opacity-90">{modelIncident.message}</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setQuickModelOpen(true)}
                  className="self-start sm:self-center min-h-[36px] rounded-lg border border-amber-400/70 bg-white/90 px-3 py-1.5 text-[11px] font-medium text-amber-950 hover:bg-white dark:border-amber-600/50 dark:bg-amber-900/50 dark:text-amber-100 dark:hover:bg-amber-900 transition-colors whitespace-nowrap shrink-0 cursor-pointer"
                >
                  Switch Model
                </button>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Simple Interactive Prompt Composer */}
          <motion.form
            onSubmit={handleSubmit}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.36, delay: 0.04, ease: [0.16, 1, 0.3, 1] }}
            className="mist-composer-shell mt-5 border border-transparent p-5 sm:p-6 focus-within:border-pink-400/50 dark:focus-within:border-pink-500/40 transition-colors"
          >
            <label htmlFor="mist-prompt-input" className="sr-only">
              Describe the website you want to build
            </label>
            <textarea
              ref={promptInputRef}
              id="mist-prompt-input"
              rows={3}
              value={promptInput}
              onChange={(e) => {
                setPromptInput(e.target.value);
                if (promptValidationError) setPromptValidationError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  e.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder={animatedPlaceholder}
              className="w-full resize-none bg-transparent text-sm sm:text-base text-zinc-950 placeholder:text-zinc-400 focus:outline-none dark:text-zinc-100 dark:placeholder:text-zinc-500"
            />

            {/* Live AI Build Activity Feed while generating */}
            <AnimatePresence>
              {isGenerating && streamProgress && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  aria-live="polite"
                  className="mt-3 overflow-hidden rounded-xl border border-blue-500/30 bg-gradient-to-br from-blue-50/90 via-violet-50/70 to-white p-3.5 text-xs dark:border-blue-500/30 dark:from-blue-950/35 dark:via-indigo-950/25 dark:to-zinc-900/90"
                >
                  <div className="relative h-1 w-full overflow-hidden rounded-full bg-blue-500/15 mb-3">
                    <div className="mist-shimmer-bar absolute inset-y-0 left-0 w-1/2 rounded-full mist-primary-gradient" />
                  </div>

                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <MistMark className="h-4 w-4 text-blue-600 dark:text-blue-400 shrink-0 animate-pulse" title="Building" />
                      <span className="font-semibold text-zinc-950 dark:text-white truncate">
                        {streamProgress.activeFile
                          ? `Writing ${streamProgress.activeFile}...`
                          : streamProgress.phase}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400 tabular-nums">
                        {elapsedSeconds}s
                        {streamProgress.charsReceived > 0
                          ? ` · ${Math.max(1, Math.round(streamProgress.charsReceived / 1024))} KB`
                          : ''}
                      </span>
                      <button
                        type="button"
                        onClick={onCancelGeneration}
                        className="rounded-lg border border-zinc-300/80 bg-white/90 px-2 py-0.5 text-[11px] font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 cursor-pointer"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>

                  {streamProgress.searchState && streamProgress.searchState !== 'idle' && (
                    <div className="mt-2 rounded-lg border border-zinc-200/80 bg-white/80 px-2.5 py-2 text-[11px] dark:border-zinc-800 dark:bg-zinc-950/60">
                      <div className="flex items-center justify-between gap-2">
                        <span className="inline-flex items-center gap-1.5 font-medium text-zinc-800 dark:text-zinc-200">
                          {streamProgress.searchState === 'searching' ? (
                            <Loader2 className="h-3 w-3 animate-spin text-blue-500" aria-hidden="true" />
                          ) : streamProgress.searchState === 'failed' ? (
                            <AlertTriangle className="h-3 w-3 text-amber-500" aria-hidden="true" />
                          ) : (
                            <Globe className="h-3 w-3 text-emerald-500" aria-hidden="true" />
                          )}
                          <span>
                            {streamProgress.searchState === 'searching'
                              ? 'Searching live web sources...'
                              : streamProgress.searchState === 'failed'
                                ? 'Web search failed'
                                : `Retrieved ${streamProgress.searchSources?.length ?? 0} verified web source${
                                    (streamProgress.searchSources?.length ?? 0) === 1 ? '' : 's'
                                  }`}
                          </span>
                        </span>
                      </div>
                      {streamProgress.searchQueries && streamProgress.searchQueries.length > 0 && (
                        <p className="mt-1 font-mono text-[10px] text-zinc-500 dark:text-zinc-400 truncate">
                          {streamProgress.searchQueries.join(' · ')}
                        </p>
                      )}
                      {streamProgress.searchError && (
                        <p className="mt-1 text-[10px] text-amber-700 dark:text-amber-300">
                          {streamProgress.searchError}
                        </p>
                      )}
                    </div>
                  )}

                  {streamProgress.completedFiles.length > 0 && (
                    <div className="mt-2.5 flex flex-wrap gap-2 text-[11px]">
                      {streamProgress.completedFiles.map((filePath) => (
                        <span
                          key={filePath}
                          className="inline-flex items-center gap-1 font-mono text-emerald-700 dark:text-emerald-400"
                        >
                          <CheckCircle2 className="h-3 w-3 shrink-0" aria-hidden="true" />
                          <span>{filePath}</span>
                        </span>
                      ))}
                      {streamProgress.activeFile && (
                        <span className="inline-flex items-center gap-1 font-mono text-blue-600 dark:text-blue-400">
                          <Loader2 className="h-3 w-3 animate-spin shrink-0" aria-hidden="true" />
                          <span>{streamProgress.activeFile}</span>
                        </span>
                      )}
                    </div>
                  )}
                </motion.div>
              )}
            </AnimatePresence>

            {(promptValidationError || generationError) && (
              <div
                role="alert"
                className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-2.5 text-xs font-medium text-red-700 dark:border-red-900/60 dark:bg-red-950/50 dark:text-red-300"
              >
                <span>{promptValidationError || generationError}</span>
                {!hasApiKey && (
                  <button
                    type="button"
                    onClick={onOpenProviders}
                    className="rounded-lg bg-red-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-red-700 cursor-pointer"
                  >
                    Configure BYOK Key
                  </button>
                )}
              </div>
            )}

            <div className="mt-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 border-t border-zinc-200/80 pt-3.5 dark:border-zinc-800/80">
              <div className="grid grid-cols-2 sm:flex sm:flex-wrap items-center gap-1.5 min-w-0">
                <button
                  type="button"
                  aria-expanded={quickModelOpen}
                  onClick={() => setQuickModelOpen((v) => !v)}
                  className={`inline-flex min-h-[44px] sm:min-h-[34px] items-center justify-between sm:justify-start gap-1 rounded-xl border px-2.5 py-1.5 text-xs font-medium transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
                    activeIncidentMatches(modelIncident, providerConfig)
                      ? 'border-amber-400/70 bg-amber-50 text-amber-900 dark:border-amber-700/70 dark:bg-amber-950/50 dark:text-amber-200'
                      : !hasApiKey
                        ? 'border-blue-400/70 bg-blue-50/90 text-blue-800 dark:border-blue-700/60 dark:bg-blue-950/40 dark:text-blue-200'
                        : 'border-zinc-200 bg-zinc-50 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800'
                  }`}
                >
                  <span className="inline-flex items-center gap-1.5 min-w-0">
                    <Cpu className="h-3.5 w-3.5 shrink-0 text-blue-600 dark:text-blue-400" aria-hidden="true" />
                    <span className="max-w-[96px] sm:max-w-[116px] truncate">{providerLabel}</span>
                    {!hasApiKey ? (
                      <span className="hidden sm:inline text-[10px] font-semibold text-blue-600 dark:text-blue-300">
                        · Add key
                      </span>
                    ) : null}
                  </span>
                  <motion.span
                    animate={{ rotate: quickModelOpen ? 180 : 0 }}
                    transition={{ duration: 0.18 }}
                    className="inline-flex shrink-0"
                  >
                    <ChevronDown className="h-3.5 w-3.5 opacity-70" aria-hidden="true" />
                  </motion.span>
                </button>

                <motion.button
                  type="button"
                  whileTap={{ scale: 0.96 }}
                  onClick={onOpenVoiceChat}
                  className="inline-flex min-h-[44px] sm:min-h-[34px] items-center justify-center sm:justify-start gap-1.5 rounded-xl border border-zinc-200 bg-zinc-50 px-2.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800 transition-colors whitespace-nowrap shrink-0 cursor-pointer"
                >
                  <Mic className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400" aria-hidden="true" />
                  <span>Voice Chat</span>
                </motion.button>

                <label className="col-span-2 sm:col-span-1 inline-flex min-h-[38px] sm:min-h-[34px] items-center gap-1 rounded-xl border border-zinc-200 bg-zinc-50 px-2 text-[11px] font-medium text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
                  <Terminal
                    className={`h-3.5 w-3.5 shrink-0 ${
                      appAiActiveForPrompt ? 'text-blue-600 dark:text-blue-400' : 'text-zinc-400'
                    }`}
                    aria-hidden="true"
                  />
                  <select
                    aria-label="Generated App AI behavior"
                    value={appAiMode}
                    onChange={(e) => onChangeAppAiMode(e.target.value as AppAiMode)}
                    className="bg-transparent text-[11px] font-medium text-zinc-700 dark:text-zinc-200 focus:outline-none cursor-pointer"
                  >
                    <option value="on_request" className="bg-white dark:bg-zinc-900">
                      App AI: On Request
                    </option>
                    <option value="off" className="bg-white dark:bg-zinc-900">
                      App AI: Off
                    </option>
                    <option value="always" className="bg-white dark:bg-zinc-900">
                      App AI: Always
                    </option>
                  </select>
                </label>

                <label className="col-span-2 sm:col-span-1 inline-flex min-h-[38px] sm:min-h-[34px] items-center gap-1 rounded-xl border border-zinc-200 bg-zinc-50 px-2 text-[11px] font-medium text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
                  <Globe
                    className={`h-3.5 w-3.5 shrink-0 ${
                      webSearchMode === 'on'
                        ? 'text-blue-600 dark:text-blue-400'
                        : webSearchMode === 'auto'
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-zinc-400'
                    }`}
                    aria-hidden="true"
                  />
                  <select
                    aria-label="Search Web mode"
                    value={webSearchMode}
                    onChange={(e) => onChangeWebSearchMode(e.target.value as WebSearchMode)}
                    className="bg-transparent text-[11px] font-medium text-zinc-700 dark:text-zinc-200 focus:outline-none cursor-pointer"
                  >
                    <option value="auto" className="bg-white dark:bg-zinc-900">
                      Search: Auto
                    </option>
                    <option value="on" className="bg-white dark:bg-zinc-900">
                      Search: On
                    </option>
                    <option value="off" className="bg-white dark:bg-zinc-900">
                      Search: Off
                    </option>
                  </select>
                </label>
                {webSearchMode === 'on' && !hasWebSearchKey && (
                  <button
                    type="button"
                    onClick={onOpenSettings}
                    className="col-span-2 sm:col-span-1 inline-flex min-h-[34px] items-center justify-center rounded-xl border border-amber-300/80 bg-amber-50 px-2.5 text-[11px] font-medium text-amber-800 hover:bg-amber-100 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-300 cursor-pointer whitespace-nowrap"
                  >
                    Configure Search Key
                  </button>
                )}
              </div>

              <div className="flex flex-col-reverse sm:flex-row sm:items-center justify-between sm:justify-end gap-2 sm:gap-2.5 shrink-0">
                {!user && (
                  <span className="text-center sm:text-right text-[11px] text-zinc-500 dark:text-zinc-400 whitespace-nowrap">
                    You'll sign in first, your prompt is kept
                  </span>
                )}
                <motion.button
                  type="submit"
                  whileHover={{ y: -1 }}
                  whileTap={{ scale: 0.97 }}
                  disabled={isGenerating}
                  className="inline-flex min-h-[48px] sm:min-h-[38px] w-full sm:w-auto items-center justify-center gap-2 rounded-xl mist-primary-gradient px-4 py-2 text-sm font-medium text-white shadow-md shadow-blue-600/20 disabled:opacity-60 transition-all whitespace-nowrap shrink-0 cursor-pointer"
                >
                  {isGenerating ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                      <span>Building Website...</span>
                    </>
                  ) : (
                    <>
                      <MistMark className="h-4 w-4" title="Generate" />
                      <span>Generate Website</span>
                      <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                    </>
                  )}
                </motion.button>
              </div>
            </div>

            {/* Expandable Quick BYOK Model & Gateway Drawer */}
            <AnimatePresence initial={false}>
              {quickModelOpen && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
                  className="overflow-hidden"
                >
                  <div className="mt-4 space-y-3 rounded-xl border border-zinc-200 bg-white/95 p-3.5 text-xs dark:border-zinc-800 dark:bg-zinc-950/95">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-[11px] font-medium text-zinc-500 dark:text-zinc-400 mr-1">
                          Preset:
                        </span>
                        {CUSTOM_GATEWAY_PRESETS.map((gw) => (
                          <button
                            key={gw.id}
                            type="button"
                            onClick={() => {
                              catalogAbortRef.current?.abort();
                              catalogSeqRef.current += 1;
                              setLiveModels(null);
                              setCatalogSource('preset');
                              setLastRefreshedAt(null);
                              setIsOutdatedFallback(false);
                              setCatalogError(null);
                              onSaveProvider({
                                ...providerConfig,
                                provider: 'custom',
                                name: gw.name,
                                baseUrl: gw.baseUrl || providerConfig.baseUrl || '',
                                model: gw.models[0]?.id || '',
                              });
                            }}
                            className={`min-h-[28px] rounded-lg border px-2.5 py-0.5 text-[11px] font-medium transition-colors cursor-pointer ${
                              activeGatewayId === gw.id
                                ? 'border-blue-500/70 bg-blue-500/10 text-blue-700 dark:text-blue-300'
                                : 'border-zinc-200 text-zinc-600 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-900'
                            }`}
                          >
                            {gw.name}
                          </button>
                        ))}
                      </div>

                      <button
                        type="button"
                        onClick={onOpenProviders}
                        className="text-[11px] font-medium text-blue-600 hover:underline dark:text-blue-400 cursor-pointer"
                      >
                        Configure Name, URL &amp; Key &rarr;
                      </button>
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-zinc-200/80 bg-zinc-50 px-2.5 py-1.5 text-[11px] text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-400">
                      <span>
                        Active Key:{' '}
                        <span className="font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                          {maskApiKey(providerConfig.apiKey) || 'Not set'}
                        </span>
                      </span>
                      <span>
                        {user?.email
                          ? providerConfig.sessionOnlyKey
                            ? 'Session RAM only'
                            : `Encrypted vault: ${user.email}`
                          : 'Sign in to sync key to account'}
                      </span>
                    </div>

                    <ModelSelectorDropdown
                      provider="custom"
                      value={providerConfig.model}
                      modelsOverride={liveModels !== null ? liveModels : activeGateway.models}
                      gatewayLabel={providerDisplayName}
                      isLoadingCatalog={isLoadingCatalog}
                      isLiveCatalog={catalogSource === 'live'}
                      catalogSource={catalogSource}
                      lastRefreshedAt={lastRefreshedAt}
                      isOutdatedFallback={isOutdatedFallback}
                      catalogError={catalogError}
                      catalogNote={catalogNote}
                      onRefreshCatalog={() => void loadQuickCatalog(true)}
                      compact
                      onChange={(nextModel) =>
                        onSaveProvider({
                          ...providerConfig,
                          provider: 'custom',
                          model: nextModel,
                        })
                      }
                    />
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.form>

    </>
  );

  const thumbGradient = (seed: string) => {
    const palettes = [
      'from-(--mist-c1) via-(--mist-c2) to-(--mist-c3)',
      'from-(--mist-c5) via-(--mist-c4) to-(--mist-c3)',
      'from-(--mist-c2) via-(--mist-c3) to-(--mist-c4)',
      'from-(--mist-c1) via-(--mist-c5) to-(--mist-c4)',
      'from-(--mist-c3) via-(--mist-c2) to-(--mist-c1)',
      'from-(--mist-c4) via-(--mist-c5) to-(--mist-c1)',
    ];
    let h = 0;
    for (let i = 0; i < seed.length; i++) h = (Math.imul(h, 31) + seed.charCodeAt(i) * (i + 7)) >>> 0;
    return palettes[h % palettes.length];
  };

  // ================= SIGNED-OUT: marketing landing =================
  if (!user) {
    const features = [
      { icon: Mic, title: 'Talk it into existence', body: 'Describe your idea out loud in Voice Studio and watch Mist turn it into a working site.' },
      { icon: KeyRound, title: 'Your keys, your models', body: 'Bring any OpenRouter or OpenAI-compatible model. Keys are stored encrypted in your account.' },
      { icon: Layers, title: 'Click to edit', body: 'Select any element in the preview and change it visually, or ask the chat to refine it.' },
      { icon: Globe, title: 'Real web research', body: 'Turn on web search and Mist cites live sources inside the sites it builds.' },
      { icon: Gamepad2, title: 'Beyond websites', body: 'Build 2D canvas games and interactive Three.js 3D scenes from the same prompt box.' },
      { icon: Download, title: 'Own the code', body: 'Download clean React + TypeScript source and host it free anywhere — no lock-in.' },
    ];
    const ideas = [
      { img: templateCoffeeImg, title: 'Coffee roastery', tag: 'Hospitality', prompt: 'Minimalist Tokyo specialty coffee roastery landing page with single-origin menu, brew guide, and location details.' },
      { img: templateAudioImg, title: 'Audio hardware', tag: 'Product', prompt: 'Premium audio hardware product page with specs, sound signature chart, and pre-order section.' },
      { img: templateArchitectImg, title: 'Architecture studio', tag: 'Portfolio', prompt: 'Architecture studio portfolio with a project grid, case study pages, and contact form.' },
      { img: templateSkincareImg, title: 'Botanical skincare', tag: 'Store', prompt: 'Botanical skincare brand store with product cards, ingredient glossary, and cart.' },
    ];
    const buildSteps = [
      { label: 'Reading your idea', done: true },
      { label: 'Planning 4 sections', done: true },
      { label: 'Writing 12 files', done: false },
    ];
    return (
      <div className="mist-ambient-canvas min-h-screen text-[#121214] dark:text-[#F4F4F5] flex flex-col overflow-x-hidden">
        <header className="sticky top-0 z-30 border-b border-zinc-900/[0.06] bg-[var(--mist-canvas)]/80 backdrop-blur-xl dark:border-white/[0.06]">
          <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-6 px-4 sm:px-6">
            <a href="#top" className="shrink-0 focus:outline-none"><MistLogo size="md" /></a>
            <nav aria-label="Primary" className="hidden md:flex items-center gap-6 text-sm text-zinc-600 dark:text-zinc-400">
              {[['#ideas', 'Ideas'], ['#features', 'Features'], ['#how', 'How it works']].map(([href, label]) => (
                <a key={href} href={href} className="hover:text-zinc-950 dark:hover:text-white transition-colors">{label}</a>
              ))}
            </nav>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={onOpenMistCode}
                className="hidden sm:inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-zinc-700 hover:text-zinc-950 bg-zinc-900/[0.04] hover:bg-zinc-900/[0.08] dark:text-zinc-300 dark:hover:text-white dark:bg-white/[0.06] dark:hover:bg-white/[0.12] border border-zinc-200/60 dark:border-white/10 transition-all cursor-pointer shadow-sm group"
                title="Mist Code Desktop Companion"
              >
                <Terminal className="h-3.5 w-3.5 text-blue-500 dark:text-blue-400 group-hover:scale-110 transition-transform" />
                <span>Mist Code</span>
              </button>
              {themeButton}
              <button type="button" onClick={onOpenAccount} className="hidden sm:inline-flex h-9 items-center rounded-lg px-3 text-sm font-medium text-zinc-700 hover:bg-zinc-900/5 dark:text-zinc-300 dark:hover:bg-white/10 transition-colors cursor-pointer">Sign in</button>
              <button type="button" onClick={onOpenAccount} className="inline-flex h-9 items-center gap-1.5 rounded-lg mist-primary-gradient px-3.5 text-sm font-semibold cursor-pointer">Create account</button>
            </div>
          </div>
        </header>

        <main id="top" className="flex-1">
          <section className="mist-hero-aurora mx-auto grid max-w-6xl items-start gap-12 px-4 sm:px-6 pt-14 pb-20 sm:pt-20 lg:grid-cols-[1.15fr_0.85fr] lg:gap-14 lg:pt-24">
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }} className="min-w-0">
              <p className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-zinc-500">
                <span className="h-1.5 w-1.5 rounded-full mist-primary-gradient" /> prompt · preview · publish
              </p>
              <h1 className="mt-5 font-display text-[42px] sm:text-6xl font-semibold leading-[1.0] text-zinc-950 dark:text-white [text-wrap:balance]">
                Say the idea.<br /><span className="mist-gradient-text">Watch it take shape.</span>
              </h1>
              <p className="mt-5 max-w-lg text-base sm:text-lg text-zinc-600 dark:text-zinc-400">
                Mist writes a real React site from one sentence, lets you click anything to change it, and hands you the code.
              </p>
              <div className="mt-8">{composerBlock}</div>
            </motion.div>

            <motion.div aria-hidden="true" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.15, ease: [0.16, 1, 0.3, 1] }} className="hidden lg:block sticky top-24">
              <div className="mist-mesh mist-grain relative overflow-hidden rounded-[22px] p-5 shadow-2xl shadow-zinc-900/10">
                <div className="relative z-10 overflow-hidden rounded-xl bg-white/90 shadow-lg backdrop-blur dark:bg-zinc-950/85">
                  <div className="flex items-center gap-1.5 border-b border-zinc-900/5 px-3 py-2 dark:border-white/5">
                    <span className="h-2.5 w-2.5 rounded-full bg-zinc-300 dark:bg-zinc-700" /><span className="h-2.5 w-2.5 rounded-full bg-zinc-300 dark:bg-zinc-700" /><span className="h-2.5 w-2.5 rounded-full bg-zinc-300 dark:bg-zinc-700" />
                    <span className="ml-3 rounded-md bg-zinc-100 px-2 py-0.5 font-mono text-[10px] text-zinc-500 dark:bg-zinc-900">kyoto-roastery.mist.app</span>
                  </div>
                  <div className="space-y-3 p-4">
                    <div className="h-24 rounded-lg mist-mesh opacity-80" />
                    <div className="h-3 w-2/3 rounded bg-zinc-200 dark:bg-zinc-800" />
                    <div className="h-3 w-1/2 rounded bg-zinc-200 dark:bg-zinc-800" />
                    <div className="grid grid-cols-3 gap-2 pt-1">
                      {[0, 1, 2].map((i) => <div key={i} className="h-14 rounded-md bg-zinc-100 dark:bg-zinc-900" />)}
                    </div>
                  </div>
                </div>
                <div className="relative z-10 mt-4 rounded-xl bg-zinc-950/85 p-3.5 font-mono text-[11px] text-zinc-300 backdrop-blur">
                  {buildSteps.map((step) => (
                    <p key={step.label} className="flex items-center gap-2 py-0.5">
                      {step.done ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" /> : <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400" />}
                      {step.label}
                    </p>
                  ))}
                </div>
              </div>
            </motion.div>
          </section>

          <section id="ideas" className="mx-auto max-w-6xl px-4 sm:px-6 py-16">
            <div className="flex items-end justify-between gap-4 border-t border-zinc-900/[0.07] pt-10 dark:border-white/[0.07]">
              <div>
                <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-zinc-500">01 — Ideas</p>
                <h2 className="mt-2 font-display text-3xl sm:text-4xl font-semibold text-zinc-950 dark:text-white">Borrow a starting point</h2>
              </div>
              <p className="hidden sm:block max-w-xs text-sm text-zinc-500">Tap one and its prompt lands in the box above, ready to tweak.</p>
            </div>
            <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {ideas.map((idea) => (
                <button key={idea.title} type="button" onClick={() => focusComposer(idea.prompt)} className="group relative aspect-[4/5] overflow-hidden rounded-2xl text-left cursor-pointer">
                  <img src={idea.img} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover transition-transform duration-700 group-hover:scale-105" />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/75 via-black/10 to-transparent" />
                  <div className="absolute inset-x-0 bottom-0 p-4 text-white">
                    <p className="text-[11px] font-medium uppercase tracking-wider text-white/70">{idea.tag}</p>
                    <p className="mt-0.5 flex items-center justify-between font-semibold">{idea.title}<ArrowRight className="h-4 w-4 -translate-x-1 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100" aria-hidden="true" /></p>
                  </div>
                </button>
              ))}
            </div>
          </section>

          <section id="features" className="mx-auto max-w-6xl px-4 sm:px-6 py-16">
            <div className="border-t border-zinc-900/[0.07] pt-10 dark:border-white/[0.07]">
              <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-zinc-500">02 — Studio</p>
              <h2 className="mt-2 max-w-2xl font-display text-3xl sm:text-4xl font-semibold text-zinc-950 dark:text-white">Everything after the first prompt</h2>
            </div>
            <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {features.map(({ icon: Icon, title, body }, i) => (
                <div key={title} className={`relative overflow-hidden rounded-2xl p-6 ${i === 0 ? 'mist-mesh mist-grain text-zinc-950 sm:col-span-2 lg:col-span-1 lg:row-span-2 flex flex-col justify-end min-h-[220px]' : 'mist-surface-card'}`}>
                  <span className={`relative z-10 inline-flex h-9 w-9 items-center justify-center rounded-xl ${i === 0 ? 'bg-white/80 text-zinc-950' : 'bg-zinc-900/5 text-zinc-900 dark:bg-white/10 dark:text-white'}`}><Icon className="h-4.5 w-4.5" aria-hidden="true" /></span>
                  <h3 className={`relative z-10 mt-4 font-semibold ${i === 0 ? 'text-2xl' : 'text-base text-zinc-950 dark:text-white'}`}>{title}</h3>
                  <p className={`relative z-10 mt-1.5 text-sm leading-relaxed ${i === 0 ? 'text-zinc-900/80' : 'text-zinc-600 dark:text-zinc-400'}`}>{body}</p>
                </div>
              ))}
            </div>
          </section>

          <div id="how">{renderShowcaseWalkthrough()}</div>

          <section className="mx-auto max-w-6xl px-4 sm:px-6 py-16">
            <div className="mist-mesh mist-grain relative overflow-hidden rounded-[24px] px-6 py-14 sm:px-12 sm:py-16">
              <div className="relative z-10 flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <h2 className="font-display text-3xl sm:text-5xl font-semibold text-zinc-950">Your next site is one sentence away.</h2>
                  <p className="mt-3 max-w-md text-zinc-900/75">Free to start. Bring your own model key. Keep the code.</p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <button type="button" onClick={onOpenAccount} className="inline-flex h-11 items-center gap-2 rounded-lg bg-zinc-950 px-5 text-sm font-semibold text-white hover:bg-zinc-800 transition-colors cursor-pointer">Create free account <ArrowRight className="h-4 w-4" aria-hidden="true" /></button>
                  <button type="button" onClick={() => focusComposer()} className="inline-flex h-11 items-center rounded-lg bg-white/70 px-5 text-sm font-semibold text-zinc-950 hover:bg-white transition-colors cursor-pointer">Try the prompt</button>
                </div>
              </div>
            </div>
          </section>
        </main>

        <footer className="border-t border-zinc-900/[0.07] py-8 dark:border-white/[0.07]">
          <div className="mx-auto flex max-w-6xl flex-col sm:flex-row items-center justify-between gap-3 px-4 sm:px-6 text-sm text-zinc-500">
            <MistLogo size="sm" />
            <span className="font-mono text-xs">ideas → websites</span>
          </div>
        </footer>
      </div>
    );
  }

  // ================= SIGNED-IN: app dashboard =================
  const navItems = [
    { icon: MistMark, label: 'New project', onClick: () => focusComposer('') },
    { icon: Search, label: 'Search', onClick: () => { document.getElementById('projects')?.scrollIntoView({ behavior: 'smooth' }); window.setTimeout(() => projectSearchRef.current?.focus(), 300); } },
    { icon: Mic, label: 'Voice Studio', onClick: onOpenVoiceChat },
    { icon: KeyRound, label: 'Models & Keys', onClick: onOpenProviders },
    { icon: Globe, label: 'Hosting', onClick: onOpenDeployments },
    { icon: Settings, label: 'Settings', onClick: onOpenSettings },
  ];
  const recent = [...projects].slice(0, 6);
  const hour = new Date().getHours();
  const greeting = hour < 5 ? 'Up late' : hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const todayLabel = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' });
  const publishedCount = projects.filter((p) => p.isPublished).length;

  return (
    <div className="mist-ambient-canvas min-h-screen text-[#121214] dark:text-[#F4F4F5] overflow-x-hidden">
      {/* Top bar */}
      <header className="sticky top-0 z-30 border-b border-zinc-900/[0.06] bg-[var(--mist-canvas)]/80 backdrop-blur-xl dark:border-white/[0.06]">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4 sm:px-6">
          <MistLogo size="md" />
          <nav aria-label="Studio" className="mx-auto hidden md:flex items-center gap-0.5 rounded-xl bg-zinc-900/[0.04] p-1 dark:bg-white/[0.05]">
            {navItems.map(({ icon: Icon, label, onClick }) => (
              <button key={label} type="button" onClick={onClick} className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium text-zinc-600 hover:bg-white hover:text-zinc-950 hover:shadow-sm dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white transition-all cursor-pointer">
                <Icon className="h-3.5 w-3.5" aria-hidden="true" />{label}
              </button>
            ))}
          </nav>
          <div className="ml-auto md:ml-0 flex items-center gap-1.5">
            <button
              type="button"
              onClick={onOpenMistCode}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-zinc-700 hover:text-zinc-950 bg-zinc-900/[0.04] hover:bg-zinc-900/[0.08] dark:text-zinc-300 dark:hover:text-white dark:bg-white/[0.06] dark:hover:bg-white/[0.12] border border-zinc-200/60 dark:border-white/10 transition-all cursor-pointer shadow-sm group"
              title="Mist Code Desktop Companion"
            >
              <Terminal className="h-3.5 w-3.5 text-blue-500 dark:text-blue-400 group-hover:scale-110 transition-transform" />
              <span>Mist Code</span>
            </button>
            {themeButton}
            <button type="button" aria-expanded={mobileMenuOpen} aria-label="Toggle menu" onClick={() => setMobileMenuOpen((v) => !v)} className="md:hidden inline-flex h-9 w-9 items-center justify-center rounded-full hover:bg-zinc-900/5 dark:hover:bg-white/10 cursor-pointer">
              {mobileMenuOpen ? <X className="h-4 w-4" aria-hidden="true" /> : <Menu className="h-4 w-4" aria-hidden="true" />}
            </button>
            <button type="button" onClick={onOpenAccount} aria-label="Account" title={user.email || 'Account'} className="rounded-full p-0.5 ring-1 ring-zinc-900/10 hover:ring-zinc-900/30 dark:ring-white/15 dark:hover:ring-white/40 transition cursor-pointer">
              {user.photoURL ? (
                <img src={user.photoURL} alt="" className="h-7 w-7 rounded-full" referrerPolicy="no-referrer" />
              ) : (
                <span className="flex h-7 w-7 items-center justify-center rounded-full mist-primary-gradient text-xs font-semibold text-white">{firstName.charAt(0).toUpperCase()}</span>
              )}
            </button>
          </div>
        </div>
        <AnimatePresence initial={false}>
          {mobileMenuOpen && (
            <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="md:hidden overflow-hidden">
              <div className="grid grid-cols-2 gap-2 p-3">
                {[...navItems, { icon: Terminal, label: 'Mist Code', onClick: () => onOpenMistCode?.() }, { icon: UserIcon, label: 'Account', onClick: onOpenAccount }].map(({ icon: Icon, label, onClick }) => (
                  <button key={label} type="button" onClick={() => { setMobileMenuOpen(false); onClick(); }} className="flex min-h-[44px] items-center gap-2 rounded-xl border border-zinc-200 bg-white/80 px-3 text-sm font-medium dark:border-zinc-800 dark:bg-zinc-900 cursor-pointer">
                    <Icon className="h-4 w-4" aria-hidden="true" />{label}
                  </button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </header>

      <main id="top">
        <div>
          <section className="mist-hero-aurora mx-auto grid max-w-6xl gap-8 px-4 sm:px-6 pt-10 pb-14 sm:pt-14 lg:grid-cols-[1fr_280px]">
            <div className="min-w-0">
              <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-zinc-500">{todayLabel}</p>
              <motion.h1 initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-2 font-display text-3xl sm:text-[44px] font-semibold leading-tight text-zinc-950 dark:text-white">
                {greeting}, <span className="mist-gradient-text">{firstName}</span>.
              </motion.h1>
              <p className="mt-1 text-zinc-500">What are we making today?</p>
              <div className="mt-6">{composerBlock}</div>
              <button type="button" onClick={() => setShowLoggedInTour((v) => !v)} className="mt-3 text-xs font-medium text-zinc-500 hover:text-zinc-900 dark:hover:text-white underline-offset-4 hover:underline cursor-pointer">
                {showLoggedInTour ? 'Hide walkthrough' : 'How Mist works'}
              </button>
            </div>
            <aside className="hidden lg:flex flex-col gap-3 pt-14">
              <div className="mist-surface-card rounded-2xl p-4">
                <p className="text-xs font-medium text-zinc-500">Your studio</p>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <div className="rounded-xl bg-zinc-900/[0.03] p-3 dark:bg-white/[0.04]"><p className="font-display text-2xl font-semibold">{projects.length}</p><p className="text-[11px] text-zinc-500">projects</p></div>
                  <div className="rounded-xl bg-zinc-900/[0.03] p-3 dark:bg-white/[0.04]"><p className="font-display text-2xl font-semibold">{publishedCount}</p><p className="text-[11px] text-zinc-500">published</p></div>
                </div>
              </div>
              <div className="mist-surface-card rounded-2xl p-2">
                <p className="px-2 pt-2 pb-1 text-xs font-medium text-zinc-500">Jump back in</p>
                {recent.length === 0 ? (
                  <p className="px-2 pb-2 text-xs text-zinc-500">Your projects will show up here.</p>
                ) : (
                  recent.slice(0, 4).map((p) => (
                    <button key={p.id} type="button" onClick={() => onOpenProject(p)} className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left text-sm hover:bg-zinc-900/5 dark:hover:bg-white/10 transition-colors cursor-pointer">
                      <span className={`h-6 w-6 shrink-0 rounded-md bg-gradient-to-br ${thumbGradient(p.id)}`} />
                      <span className="truncate">{p.name}</span>
                      <ArrowRight className="ml-auto h-3.5 w-3.5 shrink-0 text-zinc-400" aria-hidden="true" />
                    </button>
                  ))
                )}
              </div>
            </aside>
          </section>

          {showLoggedInTour && renderShowcaseWalkthrough()}

          <section id="projects" className="px-3 pb-10 sm:px-6">
            <div className="mx-auto max-w-7xl rounded-[1.75rem] border border-zinc-200/70 bg-white p-4 sm:p-6 dark:border-zinc-800/70 dark:bg-zinc-950/80">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                <div className="flex items-center gap-1 rounded-full bg-zinc-100 p-1 dark:bg-zinc-900">
                  {([['all', 'All projects'], ['published', 'Published'], ['draft', 'Drafts']] as const).map(([tab, label]) => (
                    <button key={tab} type="button" onClick={() => setProjectFilter(tab)} className={`relative rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors cursor-pointer ${projectFilter === tab ? 'text-zinc-950 dark:text-white' : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-white'}`}>
                      {projectFilter === tab && <motion.span layoutId="mist-project-filter-pill" transition={{ type: 'spring', bounce: 0.18, duration: 0.35 }} className="absolute inset-0 rounded-full bg-white shadow-sm dark:bg-zinc-800" />}
                      <span className="relative z-10">{label}</span>
                    </button>
                  ))}
                </div>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" aria-hidden="true" />
                  <input ref={projectSearchRef} type="search" aria-label="Search projects" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search projects" className="h-10 w-full md:w-64 rounded-full border border-zinc-200 bg-transparent pl-9 pr-4 text-sm placeholder:text-zinc-400 focus:border-pink-400 focus:outline-none dark:border-zinc-800" />
                </div>
              </div>

              {filteredProjects.length === 0 ? (
                <div className="mt-6 rounded-2xl border border-dashed border-zinc-300 p-10 text-center dark:border-zinc-800">
                  <FolderOpen className="mx-auto h-7 w-7 text-zinc-400" aria-hidden="true" />
                  <h3 className="mt-3 font-semibold text-zinc-900 dark:text-zinc-100">{projects.length === 0 ? 'No projects yet' : 'Nothing matches'}</h3>
                  <p className="mt-1 text-sm text-zinc-500">{projects.length === 0 ? 'Describe an idea above to create your first one.' : 'Try a different search or tab.'}</p>
                  {projects.length === 0 && (
                    <button type="button" onClick={() => focusComposer()} className="mt-5 inline-flex h-10 items-center gap-2 rounded-full mist-primary-gradient px-5 text-sm font-medium text-white cursor-pointer">Start building</button>
                  )}
                </div>
              ) : (
                <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {filteredProjects.map((project, index) => (
                    <motion.div key={project.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22, delay: Math.min(index * 0.03, 0.18) }} className="mist-project-card group rounded-[1.35rem] p-2">
                      <button type="button" onClick={() => onOpenProject(project)} className="relative block aspect-[16/10] w-full overflow-hidden rounded-2xl border border-zinc-200/70 dark:border-zinc-800 cursor-pointer">
                        <div className={`absolute inset-0 bg-gradient-to-br ${thumbGradient(project.id)} opacity-90 group-hover:scale-105 transition-transform duration-500`} />
                        <span className="absolute inset-0 flex items-center justify-center font-display text-5xl font-semibold text-white/90">{project.name.charAt(0).toUpperCase()}</span>
                        <span className="absolute left-3 top-3 rounded-full bg-black/30 px-2 py-0.5 text-[11px] font-medium text-white backdrop-blur">
                          {project.isPublished ? 'Published' : 'Draft'}
                        </span>
                        <span className="absolute inset-x-3 bottom-3 translate-y-2 opacity-0 group-hover:translate-y-0 group-hover:opacity-100 rounded-full bg-white/95 py-2 text-center text-sm font-medium text-zinc-950 transition-all">Open editor</span>
                      </button>
                      <div className="mt-3 flex items-start justify-between gap-2 px-1">
                        <div className="min-w-0">
                          <p className="truncate font-medium text-zinc-950 dark:text-white">{project.name}</p>
                          <p className="truncate text-xs text-zinc-600 dark:text-zinc-400">{project.files.length} files · {project.description || project.prompt}</p>
                        </div>
                        <div className="flex shrink-0 items-center gap-0.5 opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity">
                          <button type="button" aria-label={`Publish ${project.name}`} title="Publish (download)" onClick={() => onPublishProject(project)} className="inline-flex h-8 w-8 items-center justify-center rounded-full text-zinc-500 hover:bg-zinc-100 hover:text-zinc-950 dark:hover:bg-zinc-800 dark:hover:text-white cursor-pointer"><Download className="h-4 w-4" aria-hidden="true" /></button>
                          <button type="button" aria-label={`Duplicate ${project.name}`} title="Duplicate" onClick={() => onDuplicateProject(project)} className="inline-flex h-8 w-8 items-center justify-center rounded-full text-zinc-500 hover:bg-zinc-100 hover:text-zinc-950 dark:hover:bg-zinc-800 dark:hover:text-white cursor-pointer"><Copy className="h-4 w-4" aria-hidden="true" /></button>
                          <button type="button" aria-label={`Delete ${project.name}`} title="Delete" onClick={() => onDeleteProject(project.id)} className="inline-flex h-8 w-8 items-center justify-center rounded-full text-zinc-600 hover:text-red-700 dark:text-zinc-300 dark:hover:text-red-300 cursor-pointer"><Trash2 className="h-4 w-4" aria-hidden="true" /></button>
                        </div>
                      </div>
                    </motion.div>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}


function activeIncidentMatches(
  incident: ModelHealthIncident | null,
  config: AiProviderConfig,
): boolean {
  return Boolean(
    incident &&
      incident.provider === config.provider &&
      incident.model === config.model,
  );
}
