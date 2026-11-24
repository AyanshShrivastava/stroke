import React, { useState } from 'react';
import { FileCode2, FolderTree, Plus, Trash2 } from 'lucide-react';
import type { MistProject } from '../../types/mist';

interface WorkspaceFileDrawerProps {
  project: MistProject;
  activeFilePath: string;
  onSelectFile: (path: string) => void;
  onCreateFile: (path: string) => void;
  onDeleteFile: (path: string) => void;
}

export default function WorkspaceFileDrawer({
  project,
  activeFilePath,
  onSelectFile,
  onCreateFile,
  onDeleteFile,
}: WorkspaceFileDrawerProps) {
  const [showNewFileInput, setShowNewFileInput] = useState(false);
  const [newFilePath, setNewFilePath] = useState('');
  const [newFileError, setNewFileError] = useState<string | null>(null);

  const handleAddFile = (e: React.FormEvent) => {
    e.preventDefault();
    const cleaned = newFilePath.trim().replace(/^\/+/, '');
    if (!cleaned || !cleaned.includes('.')) {
      setNewFileError('Enter a valid path such as src/components/Footer.tsx');
      return;
    }
    if (project.files.some((f) => f.path === cleaned)) {
      setNewFileError('A file with that path already exists.');
      return;
    }
    setNewFileError(null);
    onCreateFile(cleaned);
    onSelectFile(cleaned);
    setNewFilePath('');
    setShowNewFileInput(false);
  };

  return (
    <div className="flex flex-1 flex-col min-h-0">
      <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2.5 dark:border-zinc-800">
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-400">
          <FolderTree className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Source Tree</span>
        </span>
        <button
          type="button"
          onClick={() => setShowNewFileInput((v) => !v)}
          aria-label="Create new source file"
          className="inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium text-(--mist-c2) hover:bg-(--mist-c2)/10 cursor-pointer"
        >
          <Plus className="h-3 w-3" aria-hidden="true" />
          <span>New File</span>
        </button>
      </div>

      {showNewFileInput && (
        <form
          onSubmit={handleAddFile}
          className="border-b border-zinc-200 bg-zinc-50 p-3 space-y-2 dark:border-zinc-800 dark:bg-zinc-900"
        >
          <input
            type="text"
            aria-label="New file path"
            value={newFilePath}
            onChange={(e) => setNewFilePath(e.target.value)}
            placeholder="src/components/Footer.tsx"
            className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 font-mono text-xs dark:border-zinc-700 dark:bg-zinc-950 focus:outline-none focus:border-(--mist-c2)"
          />
          {newFileError && (
            <p className="text-[11px] text-red-600 dark:text-red-400">{newFileError}</p>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowNewFileInput(false)}
              className="rounded px-2 py-1 text-[11px] text-zinc-600 dark:text-zinc-400 cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded mist-primary-gradient px-2.5 py-1 text-[11px] font-medium text-white cursor-pointer"
            >
              Add
            </button>
          </div>
        </form>
      )}

      <div className="flex-1 overflow-y-auto p-2 pb-16 space-y-0.5 mist-scrollbar">
        {project.files.map((file) => {
          const isActive = file.path === activeFilePath;
          const canDelete = file.path !== 'src/App.tsx' && file.path !== 'src/index.css';
          return (
            <div
              key={file.id}
              className={`group flex items-center justify-between rounded-md px-2.5 py-1.5 text-xs font-mono ${
                isActive
                  ? 'bg-(--mist-c2)/15 text-(--mist-c2) font-semibold'
                  : 'text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800/60'
              }`}
            >
              <button
                type="button"
                onClick={() => onSelectFile(file.path)}
                className="flex min-w-0 flex-1 items-center gap-2 text-left cursor-pointer"
              >
                <FileCode2 className="h-3.5 w-3.5 shrink-0 opacity-70" aria-hidden="true" />
                <span className="truncate">{file.path}</span>
              </button>
              {canDelete && (
                <button
                  type="button"
                  aria-label={`Delete ${file.path}`}
                  onClick={() => onDeleteFile(file.path)}
                  className="opacity-0 group-hover:opacity-100 text-zinc-400 hover:text-red-600 transition-opacity p-1 cursor-pointer"
                >
                  <Trash2 className="h-3 w-3" aria-hidden="true" />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
