import * as webpush from 'web-push';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import { SecurityValidationError } from './serverSecurity';

export interface WebPushKeys {
  p256dh: string;
  auth: string;
}

export interface WebPushSubscription {
  endpoint: string;
  expirationTime?: number | null;
  keys: WebPushKeys;
  userId?: string;
  createdAt?: string;
}

export interface NotificationPayload {
  title: string;
  body: string;
  icon?: string;
  badge?: string;
  tag?: string;
  data?: {
    url?: string;
    [key: string]: unknown;
  };
  timestamp?: number;
}

export interface VapidConfig {
  publicKey: string;
  privateKey: string;
  subject: string;
  isGenerated: boolean;
}

export interface PushSubscriptionStore {
  savePushSubscription(userId: string, subscription: WebPushSubscription): Promise<void>;
  deletePushSubscription(userId: string, endpoint: string): Promise<boolean>;
  listPushSubscriptions(userId?: string): Promise<WebPushSubscription[]>;
  deletePushSubscriptionsByEndpoints(endpoints: string[]): Promise<number>;
}

export interface PushNotificationServiceOptions {
  publicKey?: string;
  privateKey?: string;
  subject?: string;
  cacheFilePath?: string;
  store?: PushSubscriptionStore;
  allowLocalEndpointsForTesting?: boolean;
}

/**
 * Validates push subscription endpoint to protect against SSRF and arbitrary outbound requests.
 * Only recognized Web Push gateways (Google FCM, Mozilla Autopush, Apple APNs, Microsoft WNS) are allowed.
 */
export function validatePushSubscriptionEndpoint(
  endpoint: string,
  options?: { allowLocalForTesting?: boolean },
): string {
  if (!endpoint || typeof endpoint !== 'string') {
    throw new SecurityValidationError(400, 'Push subscription endpoint must be a non-empty string.');
  }

  const trimmed = endpoint.trim();
  if (trimmed.length > 2048) {
    throw new SecurityValidationError(400, 'Push subscription endpoint exceeds maximum length (2048 characters).');
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new SecurityValidationError(400, 'Push subscription endpoint is not a valid URL.');
  }

  // Allow local mock endpoints only if explicitly enabled in tests
  if (options?.allowLocalForTesting && (parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost')) {
    return trimmed;
  }

  // Protocol must strictly be HTTPS
  if (parsed.protocol !== 'https:') {
    throw new SecurityValidationError(400, 'Push subscription endpoint must use HTTPS protocol.');
  }

  // No embedded user credentials
  if (parsed.username || parsed.password) {
    throw new SecurityValidationError(400, 'Push subscription endpoint must not contain user credentials.');
  }

  const host = parsed.hostname.toLowerCase();

  // Reject raw IP addresses (IPv4 or IPv6)
  if (net.isIP(host) || /^\[.*\]$/.test(host) || /^[0-9.]+$/.test(host)) {
    throw new SecurityValidationError(400, 'Push subscription endpoint cannot be an IP address.');
  }

  // Standard HTTPS port only
  if (parsed.port && parsed.port !== '443') {
    throw new SecurityValidationError(400, 'Push subscription endpoint cannot use custom ports.');
  }

  // Hostname must match known Web Push provider domains
  const isAllowedPushProvider =
    host === 'fcm.googleapis.com' ||
    host === 'android.googleapis.com' ||
    /^([a-z0-9-]+\.)*fcm\.googleapis\.com$/i.test(host) ||
    host === 'updates.push.services.mozilla.com' ||
    /^([a-z0-9-]+\.)*push\.services\.mozilla\.com$/i.test(host) ||
    host === 'web.push.apple.com' ||
    /^([a-z0-9-]+\.)*push\.apple\.com$/i.test(host) ||
    /^([a-z0-9-]+\.)*(notify|wns)\.windows\.com$/i.test(host);

  if (!isAllowedPushProvider) {
    throw new SecurityValidationError(
      400,
      `Push subscription endpoint domain "${host}" is not a recognized Web Push service provider. Arbitrary outbound requests are forbidden.`,
    );
  }

  return trimmed;
}

/**
 * Validates client-submitted cryptographic keys.
 */
export function validatePushSubscriptionKeys(keys: unknown): WebPushKeys {
  if (!keys || typeof keys !== 'object') {
    throw new SecurityValidationError(400, 'Push subscription keys must be an object.');
  }
  const { p256dh, auth } = keys as Record<string, unknown>;
  if (typeof p256dh !== 'string' || !p256dh.trim()) {
    throw new SecurityValidationError(400, 'Push subscription p256dh key must be a non-empty string.');
  }
  if (typeof auth !== 'string' || !auth.trim()) {
    throw new SecurityValidationError(400, 'Push subscription auth key must be a non-empty string.');
  }
  const cleanP256dh = p256dh.trim();
  const cleanAuth = auth.trim();

  // Validate base64/base64url characters and reasonable lengths
  if (!/^[A-Za-z0-9_-]+={0,2}$/.test(cleanP256dh) || cleanP256dh.length < 20 || cleanP256dh.length > 256) {
    throw new SecurityValidationError(400, 'Invalid p256dh cryptographic key format.');
  }
  if (!/^[A-Za-z0-9_-]+={0,2}$/.test(cleanAuth) || cleanAuth.length < 10 || cleanAuth.length > 128) {
    throw new SecurityValidationError(400, 'Invalid auth cryptographic key format.');
  }

  return { p256dh: cleanP256dh, auth: cleanAuth };
}

/**
 * Validates and sanitizes notification payloads.
 */
export function validateNotificationPayload(raw: unknown): NotificationPayload {
  if (!raw || typeof raw !== 'object') {
    throw new SecurityValidationError(400, 'Notification payload must be an object.');
  }
  const p = raw as Record<string, unknown>;
  const title = typeof p.title === 'string' && p.title.trim() ? p.title.trim().slice(0, 120) : 'Mist Notification';
  const body = typeof p.body === 'string' ? p.body.trim().slice(0, 500) : '';
  const icon = typeof p.icon === 'string' ? p.icon.trim().slice(0, 256) : '/favicon.ico';
  const badge = typeof p.badge === 'string' ? p.badge.trim().slice(0, 256) : '/favicon.ico';
  const tag = typeof p.tag === 'string' ? p.tag.trim().slice(0, 64) : 'mist-notification';

  let dataUrl = '/';
  if (p.data && typeof p.data === 'object') {
    const rawUrl = (p.data as Record<string, unknown>).url;
    if (typeof rawUrl === 'string') {
      const trimmedUrl = rawUrl.trim();
      // Ensure url is a safe relative path or https URL
      if (trimmedUrl.startsWith('/') && !trimmedUrl.startsWith('//') && !trimmedUrl.includes('\\')) {
        dataUrl = trimmedUrl.slice(0, 500);
      } else if (trimmedUrl.startsWith('https://')) {
        try {
          const u = new URL(trimmedUrl);
          if (u.protocol === 'https:') {
            dataUrl = u.toString().slice(0, 500);
          }
        } catch {
          dataUrl = '/';
        }
      }
    }
  }

  return {
    title,
    body,
    icon,
    badge,
    tag,
    data: { url: dataUrl },
    timestamp: typeof p.timestamp === 'number' && Number.isFinite(p.timestamp) ? p.timestamp : Date.now(),
  };
}

export class PushNotificationService {
  private vapidConfig: VapidConfig;
  private subscriptions: Map<string, WebPushSubscription> = new Map();
  private store?: PushSubscriptionStore;
  private allowLocalEndpointsForTesting: boolean;

  constructor(options: PushNotificationServiceOptions = {}) {
    this.store = options.store;
    this.allowLocalEndpointsForTesting = Boolean(options.allowLocalEndpointsForTesting);
    this.vapidConfig = this.resolveVapidKeys(options);
    this.initWebPush();
  }

  private resolveVapidKeys(options: PushNotificationServiceOptions): VapidConfig {
    const envPub = (options.publicKey || process.env.VAPID_PUBLIC_KEY || '').trim();
    const envPriv = (options.privateKey || process.env.VAPID_PRIVATE_KEY || '').trim();
    const subject = (
      options.subject ||
      process.env.VAPID_SUBJECT ||
      process.env.APP_URL ||
      'mailto:admin@mistdev.ai.studio'
    ).trim();

    if (envPub && envPriv) {
      return {
        publicKey: envPub,
        privateKey: envPriv,
        subject: subject.startsWith('http') || subject.startsWith('mailto:') ? subject : `mailto:${subject}`,
        isGenerated: false,
      };
    }

    // Require persistent VAPID keys in production - never auto-generate ephemeral keys in prod
    if (process.env.NODE_ENV === 'production') {
      throw new Error(
        'Production environment requires persistent VAPID keys. Please configure VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY.',
      );
    }

    // Development fallback: try reading cached keys from local scratch/file if available to survive restarts
    const cacheFile = options.cacheFilePath || path.resolve(process.cwd(), '.vapid-cache.json');
    if (fs.existsSync(cacheFile)) {
      try {
        const raw = fs.readFileSync(cacheFile, 'utf-8');
        const parsed = JSON.parse(raw);
        if (parsed.publicKey && parsed.privateKey) {
          return {
            publicKey: parsed.publicKey,
            privateKey: parsed.privateKey,
            subject: parsed.subject || subject,
            isGenerated: true,
          };
        }
      } catch {
        // Fall back to generating new keys
      }
    }

    // Generate fresh development VAPID keys
    const generated = webpush.generateVAPIDKeys();
    const config: VapidConfig = {
      publicKey: generated.publicKey,
      privateKey: generated.privateKey,
      subject: subject.startsWith('http') || subject.startsWith('mailto:') ? subject : `mailto:${subject}`,
      isGenerated: true,
    };

    try {
      fs.writeFileSync(cacheFile, JSON.stringify(config, null, 2), 'utf-8');
    } catch {
      // Non-fatal if filesystem is read-only
    }

    // NEVER log private keys
    console.info('[Mist Notifications] Auto-generated development VAPID keys for Web Push:');
    console.info(`  VAPID_PUBLIC_KEY:  ${config.publicKey}`);
    console.info('  VAPID_PRIVATE_KEY: [REDACTED]');
    console.info(`  VAPID_SUBJECT:     ${config.subject}`);

    return config;
  }

  private initWebPush(): void {
    try {
      webpush.setVapidDetails(
        this.vapidConfig.subject,
        this.vapidConfig.publicKey,
        this.vapidConfig.privateKey,
      );
    } catch (err) {
      console.error('[Mist Notifications] Failed to initialize web-push VAPID details:', err);
    }
  }

  public getVapidPublicConfig(): { publicKey: string; subject: string; isGenerated: boolean } {
    return {
      publicKey: this.vapidConfig.publicKey,
      subject: this.vapidConfig.subject,
      isGenerated: this.vapidConfig.isGenerated,
    };
  }

  public generateNewKeypair(): { publicKey: string; privateKey: string } {
    return webpush.generateVAPIDKeys();
  }

  public async addSubscription(
    sub: { endpoint: string; expirationTime?: number | null; keys: WebPushKeys },
    userId: string,
  ): Promise<WebPushSubscription> {
    if (!userId || typeof userId !== 'string') {
      throw new SecurityValidationError(401, 'An authenticated user account is required to register a push subscription.');
    }

    const cleanEndpoint = validatePushSubscriptionEndpoint(sub.endpoint, {
      allowLocalForTesting: this.allowLocalEndpointsForTesting,
    });
    const cleanKeys = validatePushSubscriptionKeys(sub.keys);

    const record: WebPushSubscription = {
      endpoint: cleanEndpoint,
      expirationTime: typeof sub.expirationTime === 'number' ? sub.expirationTime : undefined,
      keys: cleanKeys,
      userId,
      createdAt: new Date().toISOString(),
    };

    if (this.store) {
      await this.store.savePushSubscription(userId, record);
    }
    this.subscriptions.set(cleanEndpoint, record);
    return record;
  }

  public async removeSubscription(endpoint: string, userId?: string): Promise<boolean> {
    const cleanEndpoint = (endpoint || '').trim();
    if (!cleanEndpoint) return false;

    if (this.store && userId) {
      const removed = await this.store.deletePushSubscription(userId, cleanEndpoint);
      this.subscriptions.delete(cleanEndpoint);
      return removed;
    }

    const existing = this.subscriptions.get(cleanEndpoint);
    if (existing && userId && existing.userId && existing.userId !== userId) {
      throw new SecurityValidationError(403, 'Access denied: Subscription belongs to another account.');
    }

    return this.subscriptions.delete(cleanEndpoint);
  }

  public async getSubscriptions(userId?: string): Promise<WebPushSubscription[]> {
    if (this.store) {
      const stored = await this.store.listPushSubscriptions(userId);
      for (const s of stored) {
        this.subscriptions.set(s.endpoint, s);
      }
      return stored;
    }
    const all = Array.from(this.subscriptions.values());
    if (!userId) return all;
    return all.filter((s) => s.userId === userId);
  }

  public async sendNotification(
    sub: WebPushSubscription,
    payload: NotificationPayload,
  ): Promise<{ success: boolean; statusCode?: number; error?: string }> {
    try {
      validatePushSubscriptionEndpoint(sub.endpoint, {
        allowLocalForTesting: this.allowLocalEndpointsForTesting,
      });
      const validPayload = validateNotificationPayload(payload);
      const payloadString = JSON.stringify(validPayload);

      const pushSub = {
        endpoint: sub.endpoint,
        keys: {
          p256dh: sub.keys.p256dh,
          auth: sub.keys.auth,
        },
      };

      const result = await webpush.sendNotification(pushSub, payloadString);
      return { success: true, statusCode: result.statusCode };
    } catch (err: unknown) {
      const errorObj = err as { statusCode?: number; message?: string };
      const statusCode = errorObj.statusCode || 500;
      const message = errorObj.message || String(err);

      // If subscription expired or was invalidated (404 Not Found or 410 Gone), automatically drop it
      if (statusCode === 404 || statusCode === 410) {
        if (this.store) {
          await this.store.deletePushSubscriptionsByEndpoints([sub.endpoint]);
        }
        this.subscriptions.delete(sub.endpoint);
      }

      return {
        success: false,
        statusCode,
        error: message,
      };
    }
  }

  public async sendNotificationToUser(
    userId: string,
    payload: NotificationPayload,
  ): Promise<{ sent: number; failed: number }> {
    const userSubs = await this.getSubscriptions(userId);
    let sent = 0;
    let failed = 0;

    for (const sub of userSubs) {
      const res = await this.sendNotification(sub, payload);
      if (res.success) {
        sent++;
      } else {
        failed++;
      }
    }

    return { sent, failed };
  }

  public async cleanupExpiredSubscriptions(): Promise<number> {
    const now = Date.now();
    const expiredEndpoints: string[] = [];
    const all = await this.getSubscriptions();

    for (const sub of all) {
      if (sub.expirationTime && sub.expirationTime <= now) {
        expiredEndpoints.push(sub.endpoint);
      }
    }

    if (expiredEndpoints.length > 0) {
      if (this.store) {
        await this.store.deletePushSubscriptionsByEndpoints(expiredEndpoints);
      }
      for (const ep of expiredEndpoints) {
        this.subscriptions.delete(ep);
      }
    }

    return expiredEndpoints.length;
  }

  public async broadcast(
    payload: NotificationPayload,
  ): Promise<{ sent: number; failed: number }> {
    const all = await this.getSubscriptions();
    let sent = 0;
    let failed = 0;

    for (const sub of all) {
      const res = await this.sendNotification(sub, payload);
      if (res.success) {
        sent++;
      } else {
        failed++;
      }
    }

    return { sent, failed };
  }
}

export const defaultNotificationService = new PushNotificationService();
