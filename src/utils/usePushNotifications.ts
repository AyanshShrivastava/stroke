import { useCallback, useEffect, useState } from 'react';
import type { MistUser as User } from '../types/mist';
import {
  fetchVapidConfig,
  getCurrentPushSubscription,
  getNotificationPermission,
  isPushSupported,
  registerServiceWorker,
  sendTestPushNotification,
  subscribeToPush,
  unsubscribeFromPush,
  type VapidServerConfig,
} from './pushNotifications';

export function usePushNotifications(user: User | null) {
  const [isSupported] = useState<boolean>(() => isPushSupported());
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>(() =>
    getNotificationPermission(),
  );
  const [isSubscribed, setIsSubscribed] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [vapidConfig, setVapidConfig] = useState<VapidServerConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    if (!isSupported) return;

    try {
      const perm = getNotificationPermission();
      setPermission(perm);

      const config = await fetchVapidConfig();
      setVapidConfig(config);

      const sub = await getCurrentPushSubscription();
      setIsSubscribed(Boolean(sub));
    } catch (err) {
      console.warn('[usePushNotifications] Failed to load push config or status:', err);
    }
  }, [isSupported]);

  useEffect(() => {
    if (isSupported) {
      registerServiceWorker().catch(() => {});
      refreshStatus();
    }
  }, [isSupported, refreshStatus, user]);

  const enableNotifications = useCallback(async (): Promise<boolean> => {
    setIsLoading(true);
    setError(null);
    setMessage(null);

    try {
      const idToken = user ? (await user.getIdToken().catch(() => undefined)) ?? undefined : undefined;
      const result = await subscribeToPush(idToken);

      if (result.success) {
        setIsSubscribed(true);
        setPermission(getNotificationPermission());
        setMessage('Web Push Notifications successfully enabled!');
        return true;
      } else {
        setError(result.error || 'Failed to enable notifications.');
        setPermission(getNotificationPermission());
        return false;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to subscribe.');
      return false;
    } finally {
      setIsLoading(false);
    }
  }, [user]);

  const disableNotifications = useCallback(async (): Promise<boolean> => {
    setIsLoading(true);
    setError(null);
    setMessage(null);

    try {
      const idToken = user ? (await user.getIdToken().catch(() => undefined)) ?? undefined : undefined;
      const result = await unsubscribeFromPush(idToken);

      if (result.success) {
        setIsSubscribed(false);
        setMessage('Notifications have been disabled.');
        return true;
      } else {
        setError(result.error || 'Failed to disable notifications.');
        return false;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to unsubscribe.');
      return false;
    } finally {
      setIsLoading(false);
    }
  }, [user]);

  const sendTest = useCallback(async (): Promise<boolean> => {
    setIsLoading(true);
    setError(null);
    setMessage(null);

    try {
      const idToken = user ? (await user.getIdToken().catch(() => undefined)) ?? undefined : undefined;
      const result = await sendTestPushNotification(idToken);

      if (result.success) {
        setMessage('Test notification dispatched! Check your desktop/browser notifications.');
        return true;
      } else {
        setError(result.error || 'Failed to send test notification.');
        return false;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error sending test notification.');
      return false;
    } finally {
      setIsLoading(false);
    }
  }, [user]);

  return {
    isSupported,
    permission,
    isSubscribed,
    isLoading,
    vapidConfig,
    error,
    message,
    enableNotifications,
    disableNotifications,
    sendTest,
    refreshStatus,
  };
}
