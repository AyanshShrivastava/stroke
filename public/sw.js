// Mist Service Worker for Web Push Notifications (VAPID)
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  let data = {
    title: 'Mist Notification',
    body: 'You have a new update from Mist.',
    icon: '/favicon.ico',
    badge: '/favicon.ico',
    tag: 'mist-notification',
    data: { url: '/' },
  };

  if (event.data) {
    try {
      const parsed = event.data.json();
      if (parsed && typeof parsed === 'object') {
        data = {
          title: typeof parsed.title === 'string' ? parsed.title.slice(0, 120) : data.title,
          body: typeof parsed.body === 'string' ? parsed.body.slice(0, 500) : data.body,
          icon: typeof parsed.icon === 'string' ? parsed.icon.slice(0, 256) : data.icon,
          badge: typeof parsed.badge === 'string' ? parsed.badge.slice(0, 256) : data.badge,
          tag: typeof parsed.tag === 'string' ? parsed.tag.slice(0, 64) : data.tag,
          data: parsed.data && typeof parsed.data === 'object' ? parsed.data : data.data,
        };
      }
    } catch {
      data.body = (event.data.text() || data.body).slice(0, 500);
    }
  }

  // Ensure target URL is safe relative path
  let targetUrl = '/';
  if (data.data && typeof data.data.url === 'string') {
    const rawUrl = data.data.url.trim();
    if (rawUrl.startsWith('/') && !rawUrl.startsWith('//') && !rawUrl.includes('\\')) {
      targetUrl = rawUrl;
    }
  }
  data.data = { url: targetUrl };

  const title = data.title || 'Mist';
  const options = {
    body: data.body,
    icon: data.icon || '/favicon.ico',
    badge: data.badge || '/favicon.ico',
    tag: data.tag || 'mist-notification',
    renotify: true,
    data: data.data,
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  let targetUrl = '/';
  if (event.notification.data && typeof event.notification.data.url === 'string') {
    const raw = event.notification.data.url.trim();
    if (raw.startsWith('/') && !raw.startsWith('//') && !raw.includes('\\')) {
      targetUrl = raw;
    }
  }

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ('focus' in client) {
          if (client.url && client.url.includes(self.location.origin)) {
            client.navigate(targetUrl);
            return client.focus();
          }
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
    }),
  );
});
