/**
 * Push Notification utilities using W3C Push API and VAPID.
 */

export interface VapidServerConfig {
  publicKey: string;
  subject: string;
  isGenerated: boolean;
}

export function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const buffer = new ArrayBuffer(rawData.length);
  const outputArray = new Uint8Array(buffer);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

export function isPushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  );
}

export function getNotificationPermission(): NotificationPermission | 'unsupported' {
  if (!isPushSupported()) return 'unsupported';
  return Notification.permission;
}

let swRegistrationPromise: Promise<ServiceWorkerRegistration | null> | null = null;

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!isPushSupported()) return null;

  if (swRegistrationPromise) return swRegistrationPromise;

  swRegistrationPromise = (async () => {
    try {
      const registration = await navigator.serviceWorker.register('/sw.js', {
        scope: '/',
      });
      return registration;
    } catch (err) {
      console.warn('[Push] Service worker registration failed:', err);
      return null;
    }
  })();

  return swRegistrationPromise;
}

export async function fetchVapidConfig(): Promise<VapidServerConfig> {
  const res = await fetch('/api/notifications/vapid-public-key');
  if (!res.ok) {
    throw new Error(`Failed to fetch VAPID public key (${res.status})`);
  }
  return (await res.json()) as VapidServerConfig;
}

export async function getCurrentPushSubscription(): Promise<PushSubscription | null> {
  const reg = await registerServiceWorker();
  if (!reg) return null;
  return reg.pushManager.getSubscription();
}

export async function subscribeToPush(
  idToken?: string,
): Promise<{ success: boolean; subscription?: PushSubscription; error?: string }> {
  try {
    if (!isPushSupported()) {
      return { success: false, error: 'Web Push is not supported by your browser.' };
    }

    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      return { success: false, error: `Notification permission ${permission}.` };
    }

    const reg = await registerServiceWorker();
    if (!reg) {
      return { success: false, error: 'Failed to register Service Worker.' };
    }

    const { publicKey } = await fetchVapidConfig();
    if (!publicKey) {
      return { success: false, error: 'Server did not return a valid VAPID public key.' };
    }

    const convertedVapidKey = urlBase64ToUint8Array(publicKey);

    let subscription = await reg.pushManager.getSubscription();
    if (!subscription) {
      subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: convertedVapidKey,
      });
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (idToken) {
      headers.Authorization = `Bearer ${idToken}`;
    }

    const res = await fetch('/api/notifications/subscribe', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        subscription: subscription.toJSON(),
      }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return { success: false, error: data.error || 'Server failed to save push subscription.' };
    }

    return { success: true, subscription };
  } catch (err) {
    return {
      success: false,
      error: err instanceof Error ? err.message : 'Failed to subscribe to push notifications.',
    };
  }
}

export async function unsubscribeFromPush(
  idToken?: string,
): Promise<{ success: boolean; error?: string }> {
  try {
    const reg = await registerServiceWorker();
    if (!reg) return { success: true };

    const subscription = await reg.pushManager.getSubscription();
    if (subscription) {
      const endpoint = subscription.endpoint;
      await subscription.unsubscribe();

      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      };
      if (idToken) {
        headers.Authorization = `Bearer ${idToken}`;
      }

      await fetch('/api/notifications/unsubscribe', {
        method: 'POST',
        headers,
        body: JSON.stringify({ endpoint }),
      }).catch(() => {});
    }

    return { success: true };
  } catch (err) {
    return {
      success: false,
      error: err instanceof Error ? err.message : 'Failed to unsubscribe.',
    };
  }
}

export async function sendTestPushNotification(
  idToken?: string,
): Promise<{ success: boolean; error?: string }> {
  try {
    const reg = await registerServiceWorker();
    const subscription = reg ? await reg.pushManager.getSubscription() : null;

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (idToken) {
      headers.Authorization = `Bearer ${idToken}`;
    }

    const res = await fetch('/api/notifications/test', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        subscription: subscription ? subscription.toJSON() : undefined,
      }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return { success: false, error: data.error || 'Failed to send test notification.' };
    }

    return { success: true };
  } catch (err) {
    return {
      success: false,
      error: err instanceof Error ? err.message : 'Error sending test notification.',
    };
  }
}

export async function notifyAnswerDone(projectName?: string): Promise<boolean> {
  if (typeof window === 'undefined' || !('Notification' in window)) return false;
  if (Notification.permission !== 'granted') return false;

  const title = 'Answer done! ✨';
  const body = projectName
    ? `Mist finished generating "${projectName}". Your website is ready!`
    : 'Mist finished generating your website. Click to view!';

  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg && reg.showNotification) {
      await reg.showNotification(title, {
        body,
        icon: '/favicon.ico',
        badge: '/favicon.ico',
        tag: 'mist-answer-done',
        data: { url: '/' },
      } as NotificationOptions);
      return true;
    }
  } catch {
    // Fall back to window Notification
  }

  try {
    new Notification(title, {
      body,
      icon: '/favicon.ico',
    });
    return true;
  } catch {
    return false;
  }
}
