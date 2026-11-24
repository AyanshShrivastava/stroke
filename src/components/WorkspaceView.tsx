import React, { useEffect, useState } from 'react';
import {
  ArrowLeft,
  Check,
  Code2,
  Copy,
  Cpu,
  Download,
  Eye,
  Loader2,
  MessageSquare,
  Mic,
  MousePointerClick,
  RefreshCw,
  Settings,
  SlidersHorizontal,
  User as UserIcon,
  X,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import type { MistUser as User } from '../types/mist';
import type {
  AiProviderConfig,
  AiStreamProgress,
  MistProject,
  SelectedVisualElement,
  ViewportSize,
  VisualElementPatch,
  WebSearchMode,
  WorkspaceViewMode,
} from '../types/mist';
import type { ModelHealthIncident } from '../utils/aiErrors';
import { detectGatewayFromBaseUrl } from '../data/models';
import { maskApiKey } from '../utils/projectOps';
import CodeEditor from './CodeEditor';
import VisualInspector from './VisualInspector';
import WorkspaceHeader from './workspace/WorkspaceHeader';
import WorkspaceChatDrawer from './workspace/WorkspaceChatDrawer';
import WorkspaceFileDrawer from './workspace/WorkspaceFileDrawer';
import { useAppAiBridge } from './workspace/useAppAiBridge';

interface WorkspaceViewProps {
  user: User | null;
  project: MistProject;
  providerConfig: AiProviderConfig;
  defaultViewMode?: WorkspaceViewMode;
  defaultViewport?: ViewportSize;
  webSearchMode: WebSearchMode;
  hasWebSearchKey: boolean;
  modelIncident: ModelHealthIncident | null;
  bundledHtml: string;
  bundleError: string | null;
  isBundling: boolean;
  isRefining: boolean;
  streamProgress: AiStreamProgress | null;
  refineError: string | null;
  onBackHome: () => void;
  onUpdateProjectName: (name: string) => void;
  onChangeFileContent: (path: string, content: string) => void;
  onCreateFile: (path: string) => void;
  onDeleteFile: (path: string) => void;
  onCommitVisualPatch: (patch: VisualElementPatch) => void;
  onRefineWithAi: (instruction: string, element?: SelectedVisualElement | null) => void;
  onCancelRefine: () => void;
  onChangeWebSearchMode: (mode: WebSearchMode) => void;
  onOpenVoiceChat: () => void;
  onRebundle: () => void;
  onDuplicateProject: () => void;
  onExportZip: () => void;
  onOpenDeploy: () => void;
  onOpenProviders: () => void;
  onOpenSettings: () => void;
  onOpenAccount: () => void;
  onOpenMistCode?: () => void;
}

const REFINEMENT_SUGGESTIONS = [
  'Change theme colors & polish animations',
  'Add a live AI assistant using POST /api/app-ai',
  'Improve mobile touch controls & layout',
];

export default function WorkspaceView({
  user,
  project,
  providerConfig,
  defaultViewMode = 'preview',
  defaultViewport = 'desktop',
  webSearchMode,
  hasWebSearchKey,
  modelIncident,
  bundledHtml,
  bundleError,
  isBundling,
  isRefining,
  streamProgress,
  refineError,
  onBackHome,
  onUpdateProjectName,
  onChangeFileContent,
  onCreateFile,
  onDeleteFile,
  onCommitVisualPatch,
  onRefineWithAi,
  onCancelRefine,
  onChangeWebSearchMode,
  onOpenVoiceChat,
  onRebundle,
  onDuplicateProject,
  onExportZip,
  onOpenDeploy,
  onOpenProviders,
  onOpenSettings,
  onOpenAccount,
  onOpenMistCode,
}: WorkspaceViewProps) {
  const [viewMode, setViewMode] = useState<WorkspaceViewMode>(defaultViewMode);
  const [viewport, setViewport] = useState<ViewportSize>(defaultViewport);
  const [leftTab, setLeftTab] = useState<'ai' | 'files'>('ai');

  const detectedGw = detectGatewayFromBaseUrl(providerConfig.baseUrl);
  const shortProviderLabel =
    providerConfig.name?.trim() ||
    (detectedGw === 'openrouter'
      ? 'OpenRouter'
      : detectedGw === 'groq'
        ? 'Groq'
        : detectedGw === 'gemini_byok'
          ? 'Gemini'
          : detectedGw === 'nvidia'
            ? 'NVIDIA'
            : detectedGw === 'openai'
              ? 'OpenAI'
              : 'Custom');

  const [activeFilePath, setActiveFilePath] = useState<string>(
    project.files.find((f) => f.path === 'src/App.tsx')?.path || project.files[0]?.path || 'src/App.tsx',
  );
  const [refineInput, setRefineInput] = useState('');
  const [refineValidationError, setRefineValidationError] = useState<string | null>(null);
  const [selectedElement, setSelectedElement] = useState<SelectedVisualElement | null>(null);
  const [activePane, setActivePane] = useState<'chat' | 'preview'>(() =>
    typeof window !== 'undefined' && window.innerWidth < 1024 ? 'preview' : 'chat',
  );
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  const [mobileInspectorOpen, setMobileInspectorOpen] = useState(false);
  const [refineElapsed, setRefineElapsed] = useState(0);

  const hasAppAi = Boolean(
    project.appAiEnabled ||
      project.files.some((f) => /\/api\/app-ai|window\.mistAI/.test(f.content)),
  );

  const { iframeRef, syncBridgeToIframe, handleLivePreviewPatch } = useAppAiBridge({
    hasAppAi,
    providerConfig,
    user,
    viewMode,
    onSelectElement: (el) => {
      setSelectedElement(el);
      if (typeof window !== 'undefined' && window.innerWidth < 1024) {
        setMobileInspectorOpen(true);
      }
    },
  });

  useEffect(() => {
    if (!isRefining || !streamProgress) {
      setRefineElapsed(0);
      return;
    }
    const update = () => {
      setRefineElapsed(Math.max(1, Math.floor((Date.now() - streamProgress.startedAt) / 1000)));
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [isRefining, streamProgress]);

  useEffect(() => {
    if (!project.files.some((f) => f.path === activeFilePath)) {
      setActiveFilePath(project.files[0]?.path || 'src/App.tsx');
    }
  }, [project.files, activeFilePath]);

  const handleRefineSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!refineInput.trim()) {
      setRefineValidationError('Enter a refinement instruction first.');
      return;
    }
    setRefineValidationError(null);
    onRefineWithAi(refineInput.trim(), selectedElement);
    setRefineInput('');
  };

  const iframeWidthClass =
    viewport === 'mobile'
      ? 'w-[390px]'
      : viewport === 'tablet'
        ? 'w-[768px]'
        : 'w-full';

  return (
    <div className="flex h-[100dvh] w-full flex-col overflow-hidden bg-[#FAFAFA] text-zinc-950 dark:bg-[#09090B] dark:text-zinc-100">
      {/* Top Workspace Header (Unified Desktop & Mobile) */}
      <WorkspaceHeader
        user={user}
        project={project}
        viewMode={viewMode}
        viewport={viewport}
        shortProviderLabel={shortProviderLabel}
        providerApiKey={providerConfig.apiKey}
        activePane={activePane}
        onBackHome={onBackHome}
        onUpdateProjectName={onUpdateProjectName}
        onSetViewMode={setViewMode}
        onSetViewport={setViewport}
        onSetActivePane={setActivePane}
        onOpenMobileMore={() => setMobileMoreOpen(true)}
        onOpenVoiceChat={onOpenVoiceChat}
        onOpenProviders={onOpenProviders}
        onDuplicateProject={onDuplicateProject}
        onExportZip={onExportZip}
        onOpenDeploy={onOpenDeploy}
        onOpenSettings={onOpenSettings}
        onOpenAccount={onOpenAccount}
      />

      {/* Main Workspace Body */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left Drawer: AI Refinement or Source Files */}
        <aside
          className={`${
            activePane === 'chat'
              ? 'flex w-full lg:w-[310px] xl:w-[350px]'
              : 'hidden'
          } shrink-0 flex-col border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-[#0F0F12]`}
        >
          <div className="flex border-b border-zinc-200 dark:border-zinc-800">
            <button
              type="button"
              onClick={() => setLeftTab('ai')}
              className={`flex-1 py-2.5 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
                leftTab === 'ai'
                  ? 'border-(--mist-c2) text-zinc-950 dark:text-white'
                  : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:text-zinc-400'
              }`}
            >
              AI Refine
            </button>
            <button
              type="button"
              onClick={() => setLeftTab('files')}
              className={`flex-1 py-2.5 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
                leftTab === 'files'
                  ? 'border-(--mist-c2) text-zinc-950 dark:text-white'
                  : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:text-zinc-400'
              }`}
            >
              Files ({project.files.length})
            </button>
          </div>

          {leftTab === 'ai' ? (
            <WorkspaceChatDrawer
              project={project}
              isRefining={isRefining}
              streamProgress={streamProgress}
              refineElapsed={refineElapsed}
              refineInput={refineInput}
              refineValidationError={refineValidationError}
              refineError={refineError}
              selectedElement={selectedElement}
              webSearchMode={webSearchMode}
              hasWebSearchKey={hasWebSearchKey}
              modelIncident={modelIncident}
              suggestions={REFINEMENT_SUGGESTIONS}
              onChangeRefineInput={setRefineInput}
              onClearSelectedElement={() => setSelectedElement(null)}
              onChangeWebSearchMode={onChangeWebSearchMode}
              onOpenVoiceChat={onOpenVoiceChat}
              onOpenProviders={onOpenProviders}
              onOpenSettings={onOpenSettings}
              onCancelRefine={onCancelRefine}
              onSubmitRefine={handleRefineSubmit}
            />
          ) : (
            <WorkspaceFileDrawer
              project={project}
              activeFilePath={activeFilePath}
              onSelectFile={(path) => {
                setActiveFilePath(path);
                if (viewMode === 'preview' || viewMode === 'visual') {
                  setViewMode('code');
                }
                if (typeof window !== 'undefined' && window.innerWidth < 1024) {
                  setActivePane('preview');
                }
              }}
              onCreateFile={(path) => {
                onCreateFile(path);
                setActiveFilePath(path);
                setViewMode((prev) => (prev === 'preview' ? 'code' : prev));
                if (typeof window !== 'undefined' && window.innerWidth < 1024) {
                  setActivePane('preview');
                }
              }}
              onDeleteFile={onDeleteFile}
            />
          )}
        </aside>

        {/* Center Canvas: Preview, Visual, Code, or Split */}
        <main
          className={`${
            activePane === 'chat' ? 'hidden lg:flex' : 'flex'
          } flex-1 min-w-0 flex-col bg-zinc-100 dark:bg-zinc-950`}
        >
          {/* Compact Mode Sub-Bar (< lg: mobile & tablet) */}
          <div className="flex lg:hidden shrink-0 items-center justify-between gap-2 border-b border-zinc-200 bg-white/95 px-2.5 py-1.5 dark:border-zinc-800 dark:bg-[#0F0F12]/95">
            <div
              role="tablist"
              aria-label="Canvas mode"
              className="inline-flex items-center gap-0.5 rounded-lg bg-zinc-100 p-0.5 dark:bg-zinc-900"
            >
              {(
                [
                  { id: 'preview', label: 'Preview', icon: Eye },
                  { id: 'visual', label: 'Visual', icon: MousePointerClick },
                  { id: 'code', label: 'Code', icon: Code2 },
                ] as const
              ).map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  role="tab"
                  aria-selected={viewMode === id}
                  type="button"
                  onClick={() => setViewMode(id)}
                  className={`inline-flex h-7 items-center gap-1 rounded-md px-2.5 text-xs font-medium transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
                    viewMode === id
                      ? 'bg-white text-zinc-950 shadow-xs dark:bg-zinc-800 dark:text-white'
                      : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-white'
                  }`}
                >
                  <Icon className="h-3 w-3" aria-hidden="true" />
                  <span>{label}</span>
                </button>
              ))}
            </div>

            <div className="flex items-center gap-1.5 shrink-0">
              {viewMode === 'visual' && (
                <button
                  type="button"
                  onClick={() => setMobileInspectorOpen(true)}
                  className="inline-flex h-7 items-center gap-1 rounded-md border border-zinc-200 bg-white px-2 text-xs font-medium text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 whitespace-nowrap shrink-0 cursor-pointer"
                >
                  <SlidersHorizontal className="h-3 w-3" aria-hidden="true" />
                  <span>Inspector</span>
                </button>
              )}
              {viewMode !== 'code' && (
                <button
                  type="button"
                  onClick={onRebundle}
                  aria-label="Rebuild live preview"
                  className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 cursor-pointer"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${isBundling ? 'animate-spin' : ''}`} aria-hidden="true" />
                </button>
              )}
            </div>
          </div>

          {viewMode === 'code' ? (
            <div className="flex flex-1 flex-col min-h-0">
              <CodeEditor
                files={project.files}
                activeFilePath={activeFilePath}
                onSelectFile={setActiveFilePath}
                onChangeFileContent={onChangeFileContent}
              />
            </div>
          ) : viewMode === 'split' ? (
            <div className="grid flex-1 min-h-0 grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-zinc-200 dark:divide-zinc-800">
              <div className="min-h-0 overflow-hidden">
                <CodeEditor
                  files={project.files}
                  activeFilePath={activeFilePath}
                  onSelectFile={setActiveFilePath}
                  onChangeFileContent={onChangeFileContent}
                />
              </div>
              <div className="flex flex-col min-h-0 bg-zinc-100 p-3 pb-16 dark:bg-zinc-950">
                <div className="flex items-center justify-between pb-2 text-xs text-zinc-500">
                  <span>Live Preview</span>
                  <button
                    type="button"
                    onClick={onRebundle}
                    className="inline-flex items-center gap-1 hover:text-zinc-900 dark:hover:text-white cursor-pointer"
                  >
                    <RefreshCw className={`h-3 w-3 ${isBundling ? 'animate-spin' : ''}`} aria-hidden="true" />
                    <span>Refresh</span>
                  </button>
                </div>
                <div className="flex-1 overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800">
                  <iframe
                    ref={iframeRef}
                    title="Mist Live Website Preview"
                    srcDoc={bundledHtml}
                    sandbox="allow-scripts allow-forms allow-modals allow-popups"
                    onLoad={syncBridgeToIframe}
                    className="h-full w-full border-0 bg-white"
                  />
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-1 flex-col min-h-0 p-2.5 pb-16 sm:p-4 sm:pb-16">
              {/* Preview Status Bar */}
              <div className="mb-2 hidden lg:flex items-center justify-between gap-3 text-xs">
                <div className="flex min-w-0 items-center gap-2 text-zinc-500 dark:text-zinc-400">
                  <span className="truncate font-mono text-[11px]">
                    {viewMode === 'visual'
                      ? 'Visual Editor active — click any element to edit'
                      : `Live Preview · ${viewport}`}
                  </span>
                  {bundleError && (
                    <span className="text-red-600 dark:text-red-400 font-medium whitespace-nowrap">
                      Build error
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {maskApiKey(providerConfig.apiKey) && (
                    <span className="hidden xl:inline font-mono text-[10px] text-zinc-400">
                      Key {maskApiKey(providerConfig.apiKey)}
                    </span>
                  )}
                  {project.isPublished && project.publishedSlug && (
                    <button
                      type="button"
                      onClick={onOpenDeploy}
                      className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 hover:underline dark:text-emerald-400 cursor-pointer"
                    >
                      <Check className="h-3 w-3" aria-hidden="true" />
                      <span>Exported ({project.publishedSlug}.zip)</span>
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={onRebundle}
                    aria-label="Rebuild live preview"
                    className="inline-flex items-center gap-1 rounded border border-zinc-200 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 cursor-pointer"
                  >
                    <RefreshCw className={`h-3 w-3 ${isBundling ? 'animate-spin' : ''}`} aria-hidden="true" />
                    <span>Rebuild</span>
                  </button>
                </div>
              </div>

              <div className="flex flex-1 min-h-0 justify-center overflow-hidden">
                <div
                  className={`${iframeWidthClass} relative h-full max-w-full overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm transition-all duration-200 dark:border-zinc-800`}
                >
                  {isBundling && !bundledHtml ? (
                    <div className="flex h-full w-full flex-col items-center justify-center gap-2 bg-white text-xs text-zinc-500">
                      <Loader2 className="h-5 w-5 animate-spin text-blue-600" aria-hidden="true" />
                      <span>Building preview...</span>
                    </div>
                  ) : (
                    <iframe
                      ref={iframeRef}
                      title="Mist Live Website Preview"
                      srcDoc={bundledHtml}
                      sandbox="allow-scripts allow-forms allow-modals allow-popups"
                      onLoad={syncBridgeToIframe}
                      className="h-full w-full border-0 bg-white"
                    />
                  )}
                </div>
              </div>
            </div>
          )}
        </main>

        {/* Desktop Right Visual Inspector Rail */}
        {viewMode === 'visual' && (
          <aside className="hidden lg:block w-72 xl:w-76 shrink-0 border-l border-zinc-200 bg-white dark:border-zinc-800 dark:bg-[#0F0F12]">
            <VisualInspector
              selectedElement={selectedElement}
              onLivePreviewPatch={handleLivePreviewPatch}
              onCommitPatch={onCommitVisualPatch}
              onAskAiAboutElement={(el) => {
                setSelectedElement(el);
                setLeftTab('ai');
                setActivePane('chat');
                setRefineInput(`Update the <${el.tagName}> "${el.textContent.slice(0, 40)}" to `);
              }}
            />
          </aside>
        )}

        {/* Mobile/Tablet Visual Inspector Bottom Sheet (< lg) */}
        <AnimatePresence>
          {viewMode === 'visual' && mobileInspectorOpen && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-40 flex flex-col justify-end bg-black/50 lg:hidden"
            >
              <motion.div
                initial={{ y: '100%' }}
                animate={{ y: 0 }}
                exit={{ y: '100%' }}
                transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
                className="h-[72vh] w-full rounded-t-2xl border-t border-zinc-200 bg-white shadow-2xl dark:border-zinc-800 dark:bg-[#0F0F12] flex flex-col"
              >
                <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-800">
                  <span className="font-display text-xs font-semibold text-zinc-900 dark:text-white">
                    Visual Element Inspector
                  </span>
                  <button
                    type="button"
                    aria-label="Close inspector sheet"
                    onClick={() => setMobileInspectorOpen(false)}
                    className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800 cursor-pointer"
                  >
                    <X className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>
                <div className="flex-1 min-h-0">
                  <VisualInspector
                    selectedElement={selectedElement}
                    onLivePreviewPatch={handleLivePreviewPatch}
                    onCommitPatch={onCommitVisualPatch}
                    onAskAiAboutElement={(el) => {
                      setSelectedElement(el);
                      setMobileInspectorOpen(false);
                      setActivePane('chat');
                      setLeftTab('ai');
                      setRefineInput(`Update the <${el.tagName}> "${el.textContent.slice(0, 40)}" to `);
                    }}
                  />
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Actions Bottom Sheet (< lg) */}
        <AnimatePresence>
          {mobileMoreOpen && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileMoreOpen(false)}
              className="fixed inset-0 z-40 flex items-end bg-black/55 backdrop-blur-xs lg:hidden"
            >
              <motion.div
                initial={{ y: '100%' }}
                animate={{ y: 0 }}
                exit={{ y: '100%' }}
                transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
                onClick={(e) => e.stopPropagation()}
                className="w-full rounded-t-3xl border-t border-zinc-200 bg-white p-4 pb-7 shadow-2xl dark:border-zinc-800 dark:bg-[#111115]"
              >
                <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-zinc-300 dark:bg-zinc-700" />
                <div className="mb-3 flex items-center justify-between">
                  <span className="font-display text-sm font-semibold text-zinc-950 dark:text-white">
                    Workspace Actions
                  </span>
                  <button
                    type="button"
                    aria-label="Close workspace actions"
                    onClick={() => setMobileMoreOpen(false)}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-xl text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800 cursor-pointer"
                  >
                    <X className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-2 text-xs font-medium">
                  <button
                    type="button"
                    onClick={() => {
                      setMobileMoreOpen(false);
                      onBackHome();
                    }}
                    className="col-span-2 flex min-h-[46px] items-center gap-2.5 rounded-xl border border-zinc-200 bg-zinc-50 px-3.5 text-zinc-900 dark:border-zinc-800 dark:bg-zinc-900 dark:text-white cursor-pointer"
                  >
                    <ArrowLeft className="h-4 w-4 text-blue-500" aria-hidden="true" />
                    <span>Back to Websites</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMobileMoreOpen(false);
                      onOpenVoiceChat();
                    }}
                    className="flex min-h-[46px] items-center gap-2.5 rounded-xl border border-zinc-200 bg-zinc-50 px-3.5 text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 cursor-pointer"
                  >
                    <Mic className="h-4 w-4 text-blue-500" aria-hidden="true" />
                    <span>Voice Studio</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMobileMoreOpen(false);
                      onOpenProviders();
                    }}
                    className="flex min-h-[46px] items-center justify-between gap-2 rounded-xl border border-zinc-200 bg-zinc-50 px-3.5 text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 cursor-pointer"
                  >
                    <span className="inline-flex items-center gap-2 min-w-0">
                      <Cpu className="h-4 w-4 text-blue-500 shrink-0" aria-hidden="true" />
                      <span className="truncate">{shortProviderLabel}</span>
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMobileMoreOpen(false);
                      onExportZip();
                    }}
                    className="flex min-h-[46px] items-center gap-2.5 rounded-xl border border-zinc-200 bg-zinc-50 px-3.5 text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 cursor-pointer"
                  >
                    <Download className="h-4 w-4" aria-hidden="true" />
                    <span>Export ZIP</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMobileMoreOpen(false);
                      onDuplicateProject();
                    }}
                    className="flex min-h-[46px] items-center gap-2.5 rounded-xl border border-zinc-200 bg-zinc-50 px-3.5 text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 cursor-pointer"
                  >
                    <Copy className="h-4 w-4" aria-hidden="true" />
                    <span>Duplicate</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMobileMoreOpen(false);
                      onOpenSettings();
                    }}
                    className="flex min-h-[46px] items-center gap-2.5 rounded-xl border border-zinc-200 bg-zinc-50 px-3.5 text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 cursor-pointer"
                  >
                    <Settings className="h-4 w-4" aria-hidden="true" />
                    <span>Settings</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMobileMoreOpen(false);
                      onOpenAccount();
                    }}
                    className="flex min-h-[46px] items-center gap-2.5 rounded-xl border border-zinc-200 bg-zinc-50 px-3.5 text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 cursor-pointer"
                  >
                    <UserIcon className="h-4 w-4" aria-hidden="true" />
                    <span>Account</span>
                  </button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Compact Middle-Bottom Two-Button Switcher (Chat & Preview) across Desktop, Tablet & Mobile */}
      <div className="pointer-events-none fixed inset-x-0 bottom-3 z-30 flex justify-center px-4">
        <nav
          aria-label="Workspace pane switcher"
          className="pointer-events-auto inline-flex items-center gap-1 rounded-xl border border-zinc-200/90 bg-white/95 p-1 shadow-lg shadow-zinc-950/10 backdrop-blur-md dark:border-zinc-700/80 dark:bg-[#141418]/95 dark:shadow-black/50"
        >
          <button
            type="button"
            onClick={() => setActivePane('chat')}
            aria-pressed={activePane === 'chat'}
            className={`inline-flex min-h-[34px] items-center gap-1.5 rounded-lg px-3.5 py-1 text-xs font-medium transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
              activePane === 'chat'
                ? 'bg-zinc-900 text-white shadow-xs dark:bg-white dark:text-zinc-950'
                : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-950 dark:text-zinc-400 dark:hover:bg-zinc-800/80 dark:hover:text-white'
            }`}
          >
            <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Chat</span>
          </button>
          <button
            type="button"
            onClick={() => setActivePane('preview')}
            aria-pressed={activePane === 'preview'}
            className={`inline-flex min-h-[34px] items-center gap-1.5 rounded-lg px-3.5 py-1 text-xs font-medium transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
              activePane === 'preview'
                ? 'bg-zinc-900 text-white shadow-xs dark:bg-white dark:text-zinc-950'
                : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-950 dark:text-zinc-400 dark:hover:bg-zinc-800/80 dark:hover:text-white'
            }`}
          >
            <Eye className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Preview</span>
          </button>
        </nav>
      </div>
    </div>
  );
}
