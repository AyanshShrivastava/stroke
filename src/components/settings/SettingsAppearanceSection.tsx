import React from 'react';
import { Moon, Sliders, Sun } from 'lucide-react';
import { motion } from 'motion/react';
import type { MistUser as User, StudioSettings, ViewportSize, WorkspaceViewMode } from '../../types/mist';
import NotificationSettingsCard from './NotificationSettingsCard';

interface SettingsAppearanceSectionProps {
  user: User | null;
  studioSettings: StudioSettings;
  onUpdateSettings: (partial: Partial<StudioSettings>) => void;
}

export default function SettingsAppearanceSection({
  user,
  studioSettings,
  onUpdateSettings,
}: SettingsAppearanceSectionProps) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.16 }}
      aria-labelledby="settings-appearance-heading"
      className="mist-surface-card rounded-2xl border border-zinc-200/90 p-5 sm:p-6 dark:border-zinc-800/90"
    >
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-zinc-900 text-white dark:bg-white dark:text-zinc-950 shadow-sm">
          <Sliders className="h-4 w-4" aria-hidden="true" />
        </div>
        <div>
          <h2
            id="settings-appearance-heading"
            className="font-display text-base font-semibold text-zinc-950 dark:text-white"
          >
            Appearance &amp; Workspace
          </h2>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Customize theme and default editor layout
          </p>
        </div>
      </div>

      <div className="mt-4 space-y-4 text-xs">
        <div>
          <p className="mb-1.5 font-medium text-zinc-700 dark:text-zinc-300">Studio Theme</p>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => onUpdateSettings({ theme: 'dark' })}
              className={`inline-flex min-h-[40px] items-center justify-center gap-2 rounded-xl border px-3 py-2 font-medium transition-colors cursor-pointer ${
                studioSettings.theme === 'dark'
                  ? 'border-blue-600 bg-blue-50 text-blue-700 dark:border-blue-500/70 dark:bg-blue-500/15 dark:text-blue-300'
                  : 'border-zinc-200 text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900'
              }`}
            >
              <Moon className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Dark Mode</span>
            </button>
            <button
              type="button"
              onClick={() => onUpdateSettings({ theme: 'light' })}
              className={`inline-flex min-h-[40px] items-center justify-center gap-2 rounded-xl border px-3 py-2 font-medium transition-colors cursor-pointer ${
                studioSettings.theme === 'light'
                  ? 'border-blue-600 bg-blue-50 text-blue-700 dark:border-blue-500/70 dark:bg-blue-500/15 dark:text-blue-300'
                  : 'border-zinc-200 text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900'
              }`}
            >
              <Sun className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Light Mode</span>
            </button>
          </div>
        </div>

        <div>
          <label
            htmlFor="settings-default-view"
            className="block font-medium text-zinc-700 dark:text-zinc-300"
          >
            Default Workspace Tab
          </label>
          <select
            id="settings-default-view"
            value={studioSettings.defaultViewMode}
            onChange={(e) =>
              onUpdateSettings({
                defaultViewMode: e.target.value as WorkspaceViewMode,
              })
            }
            className="mt-1.5 w-full min-h-[40px] rounded-xl border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-950 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-white"
          >
            <option value="preview">Live Preview</option>
            <option value="visual">Visual Editor</option>
            <option value="code">Code Editor</option>
            <option value="split">Split Code + Preview</option>
          </select>
        </div>

        <div>
          <label
            htmlFor="settings-default-viewport"
            className="block font-medium text-zinc-700 dark:text-zinc-300"
          >
            Default Preview Frame
          </label>
          <select
            id="settings-default-viewport"
            value={studioSettings.defaultViewport}
            onChange={(e) =>
              onUpdateSettings({
                defaultViewport: e.target.value as ViewportSize,
              })
            }
            className="mt-1.5 w-full min-h-[40px] rounded-xl border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-950 focus:border-blue-500 focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-white"
          >
            <option value="desktop">Desktop (100%)</option>
            <option value="tablet">Tablet (768px)</option>
            <option value="mobile">Mobile (390px)</option>
          </select>
        </div>

        <NotificationSettingsCard
          user={user}
          studioSettings={studioSettings}
          onUpdateSettings={onUpdateSettings}
        />
      </div>
    </motion.section>
  );
}
