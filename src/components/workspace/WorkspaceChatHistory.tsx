import React from 'react';
import { motion } from 'motion/react';
import type { AiStreamProgress, MistProject } from '../../types/mist';
import SearchSourcesCard from '../SearchSourcesCard';
import WorkspaceStreamCard from './WorkspaceStreamCard';

interface WorkspaceChatHistoryProps {
  project: MistProject;
  isRefining: boolean;
  streamProgress: AiStreamProgress | null;
  refineElapsed: number;
  onCancelRefine: () => void;
}

export default function WorkspaceChatHistory({
  project,
  isRefining,
  streamProgress,
  refineElapsed,
  onCancelRefine,
}: WorkspaceChatHistoryProps) {
  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-3 mist-scrollbar">
      {project.chatHistory.map((msg) => (
        <motion.div
          key={msg.id}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.18 }}
          className={`rounded-xl p-3 text-xs leading-relaxed ${
            msg.role === 'user'
              ? 'bg-zinc-100 text-zinc-900 dark:bg-zinc-800/90 dark:text-zinc-100'
              : 'border border-zinc-200 bg-white text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300'
          }`}
        >
          <p className="text-[11px] font-medium text-zinc-500 dark:text-zinc-400 mb-1">
            {msg.role === 'user' ? 'You' : 'Mist'}
          </p>
          <p className="whitespace-pre-wrap break-words">{msg.content}</p>
          {msg.role === 'assistant' && msg.searchOutcome && (
            <SearchSourcesCard outcome={msg.searchOutcome} compact />
          )}
          {msg.changedFiles && msg.changedFiles.length > 0 && (
            <p className="mt-2 font-mono text-[11px] text-(--mist-c2)">
              Updated: {msg.changedFiles.join(', ')}
            </p>
          )}
        </motion.div>
      ))}

      {isRefining && streamProgress && (
        <WorkspaceStreamCard
          streamProgress={streamProgress}
          refineElapsed={refineElapsed}
          onCancelRefine={onCancelRefine}
        />
      )}
    </div>
  );
}
