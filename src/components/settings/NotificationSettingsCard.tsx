import React from 'react';
import { Bell, BellRing } from 'lucide-react';
import type { MistUser as User, StudioSettings } from '../../types/mist';
import { notifyAnswerDone, subscribeToPush } from '../../utils/pushNotifications';

interface NotificationSettingsCardProps {
  user: User | null;
  studioSettings: StudioSettings;
  onUpdateSettings: (partial: Partial<StudioSettings>) => void;
}

function hasNotificationSupport(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window;
}

function getNotificationLabel(): string {
  if (!hasNotificationSupport()) {
    return 'Push notifications not supported in this browser';
  }
  if (Notification.permission === 'granted') {
    return '✓ Push alerts active';
  }
  if (Notification.permission === 'denied') {
    return '⚠ Notifications blocked in browser settings';
  }
  return 'Click test to verify';
}

async function requestNotificationPermission(): Promise<void> {
  if (!hasNotificationSupport()) return;
  if (Notification.permission === 'granted') return;
  await Notification.requestPermission();
}

async function requestPushPermission(user: User | null): Promise<void> {
  if (!hasNotificationSupport()) return;
  if (Notification.permission !== 'default') return;

  const perm = await Notification.requestPermission();
  if (perm === 'granted') {
    const idToken = user ? (await user.getIdToken().catch(() => undefined)) ?? undefined : undefined;
    void subscribeToPush(idToken).catch(() => {});
  }
}

export default function NotificationSettingsCard({
  user,
  studioSettings,
  onUpdateSettings,
}: NotificationSettingsCardProps) {
  const handleToggle = (checked: boolean) => {
    onUpdateSettings({ notifyOnAnswerDone: checked });
    if (checked) {
      void requestPushPermission(user);
    }
  };

  const handleTest = async () => {
    await requestNotificationPermission();
    void notifyAnswerDone('Test Website');
  };

  const isEnabled = studioSettings.notifyOnAnswerDone !== false;

  return (
    <div className="pt-3.5 border-t border-zinc-200/80 dark:border-zinc-800 space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 font-medium text-zinc-900 dark:text-zinc-100">
            <Bell className="h-3.5 w-3.5 text-(--mist-c3)" aria-hidden="true" />
            <span>Notify when answer is done</span>
          </div>
          <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
            Receive a browser alert ("Answer done! ✨") when generation finishes.
          </p>
        </div>

        <label className="relative inline-flex items-center cursor-pointer shrink-0">
          <input
            type="checkbox"
            checked={isEnabled}
            onChange={(e) => handleToggle(e.target.checked)}
            className="sr-only peer"
          />
          <div className="w-9 h-5 bg-zinc-300 peer-focus:outline-none rounded-full peer dark:bg-zinc-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-zinc-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all dark:border-zinc-600 peer-checked:bg-(--mist-c3)" />
        </label>
      </div>

      {isEnabled && (
        <div className="flex items-center justify-between gap-2 rounded-xl bg-zinc-100/70 px-3 py-2 dark:bg-zinc-900/60 text-[11px]">
          <span className="text-zinc-600 dark:text-zinc-400">
            {getNotificationLabel()}
          </span>
          <button
            type="button"
            onClick={() => void handleTest()}
            className="inline-flex items-center gap-1 text-(--mist-c3) hover:underline font-medium cursor-pointer"
          >
            <BellRing className="h-3 w-3" aria-hidden="true" />
            <span>Test Notification</span>
          </button>
        </div>
      )}
    </div>
  );
}
