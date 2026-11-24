import React, { useEffect, useState } from 'react';
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Cpu,
  MousePointerClick,
  Trash2,
} from 'lucide-react';
import type { SelectedVisualElement, VisualElementPatch, VisualElementStyles } from '../types/mist';

interface VisualInspectorProps {
  selectedElement: SelectedVisualElement | null;
  onLivePreviewPatch: (patch: VisualElementPatch) => void;
  onCommitPatch: (patch: VisualElementPatch) => void;
  onAskAiAboutElement: (element: SelectedVisualElement) => void;
}

const SWATCHES = ['#09090B', '#FFFFFF', '#2563EB', '#B45309', '#15803D', '#E4E4E7'];

function toSafeHex(value: string | undefined, fallback: string): string {
  if (!value) return fallback;
  return /^#[0-9a-fA-F]{6}$/.test(value) ? value.toLowerCase() : fallback;
}

export default function VisualInspector({
  selectedElement,
  onLivePreviewPatch,
  onCommitPatch,
  onAskAiAboutElement,
}: VisualInspectorProps) {
  const [textDraft, setTextDraft] = useState('');
  const [stylesDraft, setStylesDraft] = useState<VisualElementStyles>({
    color: '#09090b',
    backgroundColor: '',
    fontSize: '16px',
    fontWeight: '400',
    paddingTop: '0px',
    paddingBottom: '0px',
    paddingLeft: '0px',
    paddingRight: '0px',
    borderRadius: '0px',
    textAlign: 'left',
  });

  useEffect(() => {
    if (!selectedElement) return;
    setTextDraft(selectedElement.textContent);
    setStylesDraft(selectedElement.styles);
  }, [selectedElement]);

  if (!selectedElement) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6 text-center">
        <MousePointerClick className="h-8 w-8 text-zinc-400" aria-hidden="true" />
        <h3 className="mt-3 font-display text-sm font-semibold text-zinc-900 dark:text-white">
          Visual Inspector Ready
        </h3>
        <p className="mt-1.5 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
          Click any heading, paragraph, button, or container inside the live preview to edit its text, colors, typography, and spacing.
        </p>
      </div>
    );
  }

  const updateStyleField = (field: keyof VisualElementStyles, value: string, commit = false) => {
    const nextStyles = { ...stylesDraft, [field]: value };
    setStylesDraft(nextStyles);
    const patch: VisualElementPatch = {
      mistId: selectedElement.mistId,
      styles: { [field]: value },
    };
    onLivePreviewPatch(patch);
    if (commit) {
      onCommitPatch(patch);
    }
  };

  const commitAll = () => {
    onCommitPatch({
      mistId: selectedElement.mistId,
      originalText: selectedElement.textContent,
      newText: selectedElement.canEditText ? textDraft : undefined,
      styles: stylesDraft,
    });
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto mist-scrollbar">
      <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-xs font-semibold text-blue-600 dark:text-blue-400">
            &lt;{selectedElement.tagName}&gt;
          </span>
          <span className="font-mono text-[11px] text-zinc-400">
            #{selectedElement.mistId}
          </span>
        </div>
      </div>

      <div className="space-y-5 p-4 text-xs">
        {selectedElement.canEditText && (
          <div>
            <label
              htmlFor="mist-visual-text"
              className="block font-medium text-zinc-700 dark:text-zinc-300"
            >
              Text Content
            </label>
            <textarea
              id="mist-visual-text"
              rows={3}
              value={textDraft}
              onChange={(e) => {
                setTextDraft(e.target.value);
                onLivePreviewPatch({
                  mistId: selectedElement.mistId,
                  newText: e.target.value,
                });
              }}
              onBlur={commitAll}
              className="mt-1.5 w-full rounded-lg border border-zinc-200 bg-white px-2.5 py-2 text-xs text-zinc-900 focus:border-blue-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            />
          </div>
        )}

        {/* Colors */}
        <div className="space-y-3 border-t border-zinc-100 pt-4 dark:border-zinc-800">
          <p className="font-medium text-zinc-700 dark:text-zinc-300">Colors</p>

          <div className="flex items-center justify-between gap-2">
            <label htmlFor="mist-color-text" className="text-zinc-500 dark:text-zinc-400">
              Text Color
            </label>
            <div className="flex items-center gap-2">
              <input
                id="mist-color-text"
                type="color"
                value={toSafeHex(stylesDraft.color, '#09090b')}
                onChange={(e) => updateStyleField('color', e.target.value, true)}
                className="h-6 w-8 cursor-pointer rounded border border-zinc-200 bg-transparent p-0 dark:border-zinc-700"
              />
              <span className="w-16 truncate font-mono text-[11px] text-zinc-600 dark:text-zinc-300">
                {toSafeHex(stylesDraft.color, '#09090b')}
              </span>
            </div>
          </div>

          <div className="flex items-center justify-between gap-2">
            <label htmlFor="mist-color-bg" className="text-zinc-500 dark:text-zinc-400">
              Background
            </label>
            <div className="flex items-center gap-2">
              <input
                id="mist-color-bg"
                type="color"
                value={toSafeHex(stylesDraft.backgroundColor, '#ffffff')}
                onChange={(e) => updateStyleField('backgroundColor', e.target.value, true)}
                className="h-6 w-8 cursor-pointer rounded border border-zinc-200 bg-transparent p-0 dark:border-zinc-700"
              />
              <span className="w-16 truncate font-mono text-[11px] text-zinc-600 dark:text-zinc-300">
                {stylesDraft.backgroundColor ? toSafeHex(stylesDraft.backgroundColor, '#ffffff') : 'none'}
              </span>
            </div>
          </div>

          <div className="flex items-center justify-between gap-2 pt-1">
            <div className="flex flex-wrap gap-1.5">
              {SWATCHES.map((hex) => (
                <button
                  key={hex}
                  type="button"
                  aria-label={`Set background color ${hex}`}
                  onClick={() => updateStyleField('backgroundColor', hex, true)}
                  style={{ backgroundColor: hex }}
                  className="h-5 w-5 rounded border border-zinc-300 dark:border-zinc-700 cursor-pointer"
                />
              ))}
            </div>
            <button
              type="button"
              onClick={() => updateStyleField('backgroundColor', 'transparent', true)}
              className="text-[11px] text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 cursor-pointer"
            >
              Clear
            </button>
          </div>
        </div>

        {/* Typography */}
        <div className="space-y-3 border-t border-zinc-100 pt-4 dark:border-zinc-800">
          <p className="font-medium text-zinc-700 dark:text-zinc-300">Typography</p>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label htmlFor="mist-font-size" className="block text-[11px] text-zinc-500">
                Size
              </label>
              <input
                id="mist-font-size"
                type="text"
                value={stylesDraft.fontSize}
                onChange={(e) => updateStyleField('fontSize', e.target.value, false)}
                onBlur={commitAll}
                className="mt-1 w-full rounded border border-zinc-200 bg-white px-2 py-1 font-mono text-xs dark:border-zinc-700 dark:bg-zinc-900"
              />
            </div>
            <div>
              <label htmlFor="mist-font-weight" className="block text-[11px] text-zinc-500">
                Weight
              </label>
              <select
                id="mist-font-weight"
                value={stylesDraft.fontWeight}
                onChange={(e) => updateStyleField('fontWeight', e.target.value, true)}
                className="mt-1 w-full rounded border border-zinc-200 bg-white px-2 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
              >
                <option value="400">Regular (400)</option>
                <option value="500">Medium (500)</option>
                <option value="600">Semibold (600)</option>
                <option value="700">Bold (700)</option>
              </select>
            </div>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-zinc-500 dark:text-zinc-400">Alignment</span>
            <div className="flex items-center gap-1 rounded-md bg-zinc-100 p-0.5 dark:bg-zinc-800">
              {(
                [
                  { val: 'left', icon: AlignLeft, label: 'Align left' },
                  { val: 'center', icon: AlignCenter, label: 'Align center' },
                  { val: 'right', icon: AlignRight, label: 'Align right' },
                ] as const
              ).map(({ val, icon: Icon, label }) => (
                <button
                  key={val}
                  type="button"
                  aria-label={label}
                  onClick={() => updateStyleField('textAlign', val, true)}
                  className={`rounded p-1.5 cursor-pointer ${
                    stylesDraft.textAlign === val
                      ? 'bg-white text-zinc-950 shadow-sm dark:bg-zinc-700 dark:text-white'
                      : 'text-zinc-500 hover:text-zinc-900 dark:text-zinc-400'
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Spacing & Layout */}
        <div className="space-y-3 border-t border-zinc-100 pt-4 dark:border-zinc-800">
          <p className="font-medium text-zinc-700 dark:text-zinc-300">Spacing &amp; Radius</p>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label htmlFor="mist-pad-y" className="block text-[11px] text-zinc-500">
                Pad Y
              </label>
              <input
                id="mist-pad-y"
                type="text"
                value={stylesDraft.paddingTop}
                onChange={(e) => {
                  const val = e.target.value;
                  const next = { ...stylesDraft, paddingTop: val, paddingBottom: val };
                  setStylesDraft(next);
                  onLivePreviewPatch({
                    mistId: selectedElement.mistId,
                    styles: { paddingTop: val, paddingBottom: val },
                  });
                }}
                onBlur={commitAll}
                className="mt-1 w-full rounded border border-zinc-200 bg-white px-2 py-1 font-mono text-xs dark:border-zinc-700 dark:bg-zinc-900"
              />
            </div>
            <div>
              <label htmlFor="mist-pad-x" className="block text-[11px] text-zinc-500">
                Pad X
              </label>
              <input
                id="mist-pad-x"
                type="text"
                value={stylesDraft.paddingLeft}
                onChange={(e) => {
                  const val = e.target.value;
                  const next = { ...stylesDraft, paddingLeft: val, paddingRight: val };
                  setStylesDraft(next);
                  onLivePreviewPatch({
                    mistId: selectedElement.mistId,
                    styles: { paddingLeft: val, paddingRight: val },
                  });
                }}
                onBlur={commitAll}
                className="mt-1 w-full rounded border border-zinc-200 bg-white px-2 py-1 font-mono text-xs dark:border-zinc-700 dark:bg-zinc-900"
              />
            </div>
            <div>
              <label htmlFor="mist-radius" className="block text-[11px] text-zinc-500">
                Radius
              </label>
              <input
                id="mist-radius"
                type="text"
                value={stylesDraft.borderRadius}
                onChange={(e) => updateStyleField('borderRadius', e.target.value, false)}
                onBlur={commitAll}
                className="mt-1 w-full rounded border border-zinc-200 bg-white px-2 py-1 font-mono text-xs dark:border-zinc-700 dark:bg-zinc-900"
              />
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="space-y-2 border-t border-zinc-100 pt-4 dark:border-zinc-800">
          <button
            type="button"
            onClick={commitAll}
            className="w-full rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-700 transition-colors cursor-pointer"
          >
            Save Visual Changes
          </button>
          <button
            type="button"
            onClick={() => onAskAiAboutElement(selectedElement)}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs font-medium text-zinc-800 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700 transition-colors cursor-pointer"
          >
            <Cpu className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400" aria-hidden="true" />
            <span>Refine with AI</span>
          </button>
          <button
            type="button"
            onClick={() => {
              onLivePreviewPatch({ mistId: selectedElement.mistId, deleted: true });
              onCommitPatch({ mistId: selectedElement.mistId, deleted: true });
            }}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-900/60 dark:text-red-400 dark:hover:bg-red-950/50 transition-colors cursor-pointer"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Hide Element</span>
          </button>
        </div>
      </div>
    </div>
  );
}
