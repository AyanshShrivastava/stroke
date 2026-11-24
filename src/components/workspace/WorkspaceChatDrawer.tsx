import React from 'react';
import { AlertTriangle } from 'lucide-react';
import type {
  AiStreamProgress,
  MistProject,
  SelectedVisualElement,
  WebSearchMode,
} from '../../types/mist';
import type { ModelHealthIncident } from '../../utils/aiErrors';
import WorkspaceChatHistory from './WorkspaceChatHistory';
import WorkspaceRefineForm from './WorkspaceRefineForm';

interface WorkspaceChatDrawerProps {
  project: MistProject;
  isRefining: boolean;
  streamProgress: AiStreamProgress | null;
  refineElapsed: number;
  refineInput: string;
  refineValidationError: string | null;
  refineError: string | null;
  selectedElement: SelectedVisualElement | null;
  webSearchMode: WebSearchMode;
  hasWebSearchKey: boolean;
  modelIncident: ModelHealthIncident | null;
  suggestions: string[];
  onChangeRefineInput: (value: string) => void;
  onClearSelectedElement: () => void;
  onChangeWebSearchMode: (mode: WebSearchMode) => void;
  onOpenVoiceChat: () => void;
  onOpenProviders: () => void;
  onOpenSettings: () => void;
  onCancelRefine: () => void;
  onSubmitRefine: (e: React.FormEvent) => void;
}

export default function WorkspaceChatDrawer({
  project,
  isRefining,
  streamProgress,
  refineElapsed,
  refineInput,
  refineValidationError,
  refineError,
  selectedElement,
  webSearchMode,
  hasWebSearchKey,
  modelIncident,
  suggestions,
  onChangeRefineInput,
  onClearSelectedElement,
  onChangeWebSearchMode,
  onOpenVoiceChat,
  onOpenProviders,
  onOpenSettings,
  onCancelRefine,
  onSubmitRefine,
}: WorkspaceChatDrawerProps) {
  return (
    <div className="flex flex-1 flex-col min-h-0">
      <WorkspaceChatHistory
        project={project}
        isRefining={isRefining}
        streamProgress={streamProgress}
        refineElapsed={refineElapsed}
        onCancelRefine={onCancelRefine}
      />

      {modelIncident && (
        <div
          role="alert"
          className="mx-3 mb-2 rounded-xl border border-amber-300 bg-amber-50 p-2.5 text-[11px] text-amber-950 dark:border-amber-700/60 dark:bg-amber-950/50 dark:text-amber-200"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="font-semibold truncate">{modelIncident.title}</p>
              <button
                type="button"
                onClick={onOpenProviders}
                className="mt-1 font-medium text-amber-800 underline dark:text-amber-300 cursor-pointer"
              >
                Switch Model
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Quick Refinement Chips */}
      <div className="border-t border-zinc-100 px-3 pt-3 pb-1 dark:border-zinc-800">
        <p className="text-[11px] font-medium text-zinc-500 dark:text-zinc-400 mb-2">
          Quick refinements
        </p>
        <div className="flex flex-wrap gap-1.5">
          {suggestions.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => onChangeRefineInput(item)}
              className="rounded-md border border-zinc-200 bg-zinc-50 px-2 py-1 text-[11px] text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      <WorkspaceRefineForm
        isRefining={isRefining}
        refineInput={refineInput}
        refineValidationError={refineValidationError}
        refineError={refineError}
        selectedElement={selectedElement}
        webSearchMode={webSearchMode}
        hasWebSearchKey={hasWebSearchKey}
        onChangeRefineInput={onChangeRefineInput}
        onClearSelectedElement={onClearSelectedElement}
        onChangeWebSearchMode={onChangeWebSearchMode}
        onOpenVoiceChat={onOpenVoiceChat}
        onOpenSettings={onOpenSettings}
        onSubmitRefine={onSubmitRefine}
      />
    </div>
  );
}
