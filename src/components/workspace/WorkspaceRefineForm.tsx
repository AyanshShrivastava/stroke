import React from 'react';
import { Globe, Mic, Send } from 'lucide-react';
import type { SelectedVisualElement, WebSearchMode } from '../../types/mist';

interface WorkspaceRefineFormProps {
  isRefining: boolean;
  refineInput: string;
  refineValidationError: string | null;
  refineError: string | null;
  selectedElement: SelectedVisualElement | null;
  webSearchMode: WebSearchMode;
  hasWebSearchKey: boolean;
  onChangeRefineInput: (value: string) => void;
  onClearSelectedElement: () => void;
  onChangeWebSearchMode: (mode: WebSearchMode) => void;
  onOpenVoiceChat: () => void;
  onOpenSettings: () => void;
  onSubmitRefine: (e: React.FormEvent) => void;
}

function isEnterSubmit(e: React.KeyboardEvent): boolean {
  if (e.key !== 'Enter') return false;
  if (e.shiftKey) return false;
  return !e.nativeEvent.isComposing;
}

function getSearchIconColor(mode: WebSearchMode): string {
  if (mode === 'on') return 'text-(--mist-c2)';
  if (mode === 'auto') return 'text-emerald-600 dark:text-emerald-400';
  return 'text-zinc-400';
}

export default function WorkspaceRefineForm({
  isRefining,
  refineInput,
  refineValidationError,
  refineError,
  selectedElement,
  webSearchMode,
  hasWebSearchKey,
  onChangeRefineInput,
  onClearSelectedElement,
  onChangeWebSearchMode,
  onOpenVoiceChat,
  onOpenSettings,
  onSubmitRefine,
}: WorkspaceRefineFormProps) {
  const isSearchActive = webSearchMode === 'on';

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (isEnterSubmit(e)) {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
  };

  return (
    <form
      onSubmit={onSubmitRefine}
      className="border-t border-zinc-200 p-3 pb-16 dark:border-zinc-800"
    >
      {selectedElement && (
        <div className="mb-2 flex items-center justify-between rounded-lg bg-(--mist-c2)/10 px-2.5 py-1 text-[11px] text-(--mist-c2) dark:bg-(--mist-c2)/20">
          <span className="truncate font-mono">
            Target: &lt;{selectedElement.tagName}&gt;
          </span>
          <button
            type="button"
            aria-label="Clear selected element"
            onClick={onClearSelectedElement}
            className="ml-2 font-semibold hover:underline cursor-pointer"
          >
            Clear
          </button>
        </div>
      )}

      {(refineValidationError || refineError) && (
        <p role="alert" className="mb-2 text-[11px] font-medium text-red-600 dark:text-red-400">
          {refineValidationError || refineError}
        </p>
      )}

      <div className="mb-2 flex items-center justify-between gap-2">
        <label className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-zinc-50 px-2 py-1 text-[11px] font-medium text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
          <Globe className={`h-3 w-3 shrink-0 ${getSearchIconColor(webSearchMode)}`} aria-hidden="true" />
          <select
            aria-label="Refinement Search Web mode"
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

        {isSearchActive && !hasWebSearchKey && (
          <button
            type="button"
            onClick={onOpenSettings}
            className="text-[10px] font-medium text-amber-700 hover:underline dark:text-amber-300 cursor-pointer"
          >
            Add Search Key
          </button>
        )}
      </div>

      <label htmlFor="mist-refine-input" className="sr-only">
        Refine website with AI
      </label>
      <div className="flex items-end gap-1.5 rounded-xl border border-zinc-200 bg-zinc-50 p-2 focus-within:border-(--mist-c2) dark:border-zinc-700 dark:bg-zinc-900">
        <textarea
          id="mist-refine-input"
          rows={2}
          value={refineInput}
          onChange={(e) => onChangeRefineInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe updates, color changes, or bug fixes..."
          className="flex-1 resize-none bg-transparent text-xs text-zinc-950 placeholder:text-zinc-400 focus:outline-none dark:text-zinc-100"
        />
        <button
          type="button"
          onClick={onOpenVoiceChat}
          aria-label="Voice refine with Mist"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700 transition-colors cursor-pointer"
        >
          <Mic className="h-3.5 w-3.5 text-(--mist-c2)" aria-hidden="true" />
        </button>
        <button
          type="submit"
          disabled={isRefining}
          aria-label="Apply AI refinement"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg mist-primary-gradient text-white transition-opacity disabled:opacity-40 cursor-pointer"
        >
          <Send className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
    </form>
  );
}
