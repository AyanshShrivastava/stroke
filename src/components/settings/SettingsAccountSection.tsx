import React from 'react';
import { User as UserIcon } from 'lucide-react';
import { motion } from 'motion/react';
import type { DeploymentRecord, MistProject, MistUser as User } from '../../types/mist';

interface SettingsAccountSectionProps {
  user: User | null;
  projects: MistProject[];
  deployments: DeploymentRecord[];
  onSignIn: () => void;
}

export default function SettingsAccountSection({
  user,
  projects,
  deployments,
  onSignIn,
}: SettingsAccountSectionProps) {
  const initial = (user?.displayName || user?.email || 'M')[0].toUpperCase();

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.12 }}
      aria-labelledby="settings-account-heading"
      className="mist-surface-card rounded-2xl border border-zinc-200/90 p-5 sm:p-6 dark:border-zinc-800/90"
    >
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-600 to-teal-500 text-white shadow-sm">
          <UserIcon className="h-4 w-4" aria-hidden="true" />
        </div>
        <div>
          <h2
            id="settings-account-heading"
            className="font-display text-base font-semibold text-zinc-950 dark:text-white"
          >
            Account Profile
          </h2>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Your projects and preferences follow your sign-in
          </p>
        </div>
      </div>

      <div className="mt-4 space-y-4 text-xs">
        {user ? (
          <div className="flex items-center gap-3 rounded-xl border border-zinc-200/80 bg-white/80 p-3 dark:border-zinc-800 dark:bg-zinc-900/70">
            {user.photoURL ? (
              <img
                src={user.photoURL}
                alt={user.displayName || 'Account avatar'}
                referrerPolicy="no-referrer"
                className="h-10 w-10 rounded-full border border-zinc-200 object-cover dark:border-zinc-700"
              />
            ) : (
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-zinc-200 font-semibold text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
                {initial}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-zinc-950 dark:text-white truncate">
                {user.displayName || 'Mist Builder'}
              </p>
              <p className="text-zinc-500 dark:text-zinc-400 truncate">{user.email}</p>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-zinc-200/80 bg-zinc-50/90 p-3.5 dark:border-zinc-800 dark:bg-zinc-900/70">
            <p className="text-zinc-600 dark:text-zinc-400 leading-relaxed">
              Sign in with Google to save your websites, settings, and published deployments across devices.
            </p>
            <button
              type="button"
              onClick={onSignIn}
              className="mt-3 w-full min-h-[40px] rounded-xl mist-primary-gradient px-4 py-2 font-medium text-white shadow-sm transition-all cursor-pointer"
            >
              Continue with Google
            </button>
          </div>
        )}

        <div className="grid grid-cols-2 divide-x divide-zinc-200 rounded-xl border border-zinc-200/80 bg-white/70 text-center dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900/50">
          <div className="py-3 px-2">
            <p className="font-display text-lg font-semibold text-zinc-950 dark:text-white tabular-nums">
              {projects.length}
            </p>
            <p className="text-[11px] text-zinc-500 dark:text-zinc-400">Saved Projects</p>
          </div>
          <div className="py-3 px-2">
            <p className="font-display text-lg font-semibold text-zinc-950 dark:text-white tabular-nums">
              {deployments.length}
            </p>
            <p className="text-[11px] text-zinc-500 dark:text-zinc-400">Published Sites</p>
          </div>
        </div>
      </div>
    </motion.section>
  );
}
