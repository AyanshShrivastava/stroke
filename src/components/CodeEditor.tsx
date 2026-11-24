import React, { useState } from 'react';
import { Check, Copy, FileCode2 } from 'lucide-react';
import type { ProjectFile } from '../types/mist';

interface CodeEditorProps {
  files: ProjectFile[];
  activeFilePath: string;
  onSelectFile: (path: string) => void;
  onChangeFileContent: (path: string, content: string) => void;
}

export default function CodeEditor({
  files,
  activeFilePath,
  onSelectFile,
  onChangeFileContent,
}: CodeEditorProps) {
  const [copied, setCopied] = useState(false);

  const activeFile = files.find((f) => f.path === activeFilePath) || files[0];
  const lines = (activeFile?.content || '').split('\n');

  const handleCopy = async () => {
    if (!activeFile) return;
    try {
      await navigator.clipboard.writeText(activeFile.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard blocked in non-HTTPS iframe contexts
    }
  };

  if (!activeFile) {
    return (
      <div className="flex h-full items-center justify-center bg-zinc-950 text-xs text-zinc-400">
        Select or create a file to edit source code.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-[#0C0C0E] text-zinc-100">
      {/* File Tabs */}
      <div className="flex items-center justify-between gap-2 border-b border-zinc-800 bg-[#121215] px-2">
        <div className="flex min-w-0 flex-1 items-center overflow-x-auto mist-scrollbar">
          {files.map((file) => {
            const isActive = file.path === activeFile.path;
            return (
              <button
                key={file.id}
                type="button"
                onClick={() => onSelectFile(file.path)}
                className={`inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-mono transition-colors whitespace-nowrap shrink-0 cursor-pointer ${
                  isActive
                    ? 'border-blue-500 bg-[#0C0C0E] text-white'
                    : 'border-transparent text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <FileCode2 className="h-3.5 w-3.5 text-zinc-500" aria-hidden="true" />
                <span>{file.path}</span>
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-2 pl-2 shrink-0">
          <span className="hidden sm:inline text-[11px] font-mono text-zinc-500 tabular-nums">
            {lines.length} lines
          </span>
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1 rounded border border-zinc-700 bg-zinc-800/80 px-2.5 py-1 text-[11px] font-medium text-zinc-200 hover:bg-zinc-700 transition-colors whitespace-nowrap cursor-pointer"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-emerald-400" aria-hidden="true" />
                <span>Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" aria-hidden="true" />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Line-numbered monospace editor */}
      <div className="relative flex flex-1 overflow-auto mist-scrollbar">
        <div
          aria-hidden="true"
          className="select-none border-r border-zinc-800/80 bg-[#0F0F12] px-3 pt-4 pb-16 text-right font-mono text-xs leading-6 text-zinc-600 tabular-nums"
        >
          {lines.map((_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>
        <textarea
          aria-label={`Source code editor for ${activeFile.path}`}
          spellCheck={false}
          value={activeFile.content}
          onChange={(e) => onChangeFileContent(activeFile.path, e.target.value)}
          className="flex-1 resize-none bg-transparent p-4 pb-16 font-mono text-xs leading-6 text-zinc-100 focus:outline-none whitespace-pre overflow-x-auto"
        />
      </div>
    </div>
  );
}
