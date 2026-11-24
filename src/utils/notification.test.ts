import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import {
  PushNotificationService,
  validatePushSubscriptionEndpoint,
  validatePushSubscriptionKeys,
  validateNotificationPayload,
  type WebPushSubscription,
} from './notificationService';
import { createMistApp } from './mistServerApp';
import { InMemoryAdminStore } from '../server/firestoreAdmin';

test('PushNotificationService auto-generates VAPID keys if none provided in non-production', () => {
  const origEnv = process.env.NODE_ENV;
  try {
    delete process.env.NODE_ENV;
    const service = new PushNotificationService({
      publicKey: '',
      privateKey: '',
    });

    const config = service.getVapidPublicConfig();
    assert.ok(config.publicKey.length > 20, 'VAPID public key should be non-empty');
    assert.ok(config.subject.includes('mistdev.ai.studio'), 'Subject should contain default domain');
    assert.equal(config.isGenerated, true);
  } finally {
    process.env.NODE_ENV = origEnv;
  }
});

test('PushNotificationService requires persistent VAPID keys in production', () => {
  const origEnv = process.env.NODE_ENV;
  const origPub = process.env.VAPID_PUBLIC_KEY;
  const origPriv = process.env.VAPID_PRIVATE_KEY;

  try {
    process.env.NODE_ENV = 'production';
    delete process.env.VAPID_PUBLIC_KEY;
    delete process.env.VAPID_PRIVATE_KEY;

    assert.throws(
      () => {
        new PushNotificationService({ publicKey: '', privateKey: '' });
      },
      /Production environment requires persistent VAPID keys/,
    );
  } finally {
    process.env.NODE_ENV = origEnv;
    if (origPub) process.env.VAPID_PUBLIC_KEY = origPub;
    if (origPriv) process.env.VAPID_PRIVATE_KEY = origPriv;
  }
});

test('PushNotificationService accepts explicit VAPID keys and subject', () => {
  const keypair = new PushNotificationService().generateNewKeypair();
  const service = new PushNotificationService({
    publicKey: keypair.publicKey,
    privateKey: keypair.privateKey,
    subject: 'mailto:developer@example.com',
  });

  const config = service.getVapidPublicConfig();
  assert.equal(config.publicKey, keypair.publicKey);
  assert.equal(config.subject, 'mailto:developer@example.com');
  assert.equal(config.isGenerated, false);
});

test('validatePushSubscriptionEndpoint prevents arbitrary outbound requests (SSRF)', () => {
  // Prohibited: plain HTTP
  assert.throws(
    () => validatePushSubscriptionEndpoint('http://fcm.googleapis.com/fcm/send/123'),
    /must use HTTPS protocol/,
  );

  // Prohibited: Private / metadata IP addresses
  assert.throws(
    () => validatePushSubscriptionEndpoint('https://169.254.169.254/latest/meta-data'),
    /cannot be an IP address/,
  );
  assert.throws(
    () => validatePushSubscriptionEndpoint('https://127.0.0.1:8080/internal'),
    /cannot be an IP address/,
  );

  // Prohibited: Arbitrary unapproved external domains
  assert.throws(
    () => validatePushSubscriptionEndpoint('https://attacker-controlled-host.com/endpoint'),
    /not a recognized Web Push service provider/,
  );
  assert.throws(
    () => validatePushSubscriptionEndpoint('https://fcm.googleapis.com.attacker.com/fake'),
    /not a recognized Web Push service provider/,
  );

  // Prohibited: Custom ports and embedded credentials
  assert.throws(
    () => validatePushSubscriptionEndpoint('https://fcm.googleapis.com:8443/fcm/send/123'),
    /cannot use custom ports/,
  );
  assert.throws(
    () => validatePushSubscriptionEndpoint('https://user:pass@fcm.googleapis.com/fcm/send/123'),
    /must not contain user credentials/,
  );

  // Allowed: Google FCM / Android
  assert.equal(
    validatePushSubscriptionEndpoint('https://fcm.googleapis.com/fcm/send/sub-123'),
    'https://fcm.googleapis.com/fcm/send/sub-123',
  );
  assert.equal(
    validatePushSubscriptionEndpoint('https://android.googleapis.com/gcm/send/sub-456'),
    'https://android.googleapis.com/gcm/send/sub-456',
  );

  // Allowed: Mozilla Autopush
  assert.equal(
    validatePushSubscriptionEndpoint('https://updates.push.services.mozilla.com/wpush/v2/token123'),
    'https://updates.push.services.mozilla.com/wpush/v2/token123',
  );

  // Allowed: Apple APNs
  assert.equal(
    validatePushSubscriptionEndpoint('https://web.push.apple.com/QN1234567890'),
    'https://web.push.apple.com/QN1234567890',
  );

  // Allowed: Microsoft WNS
  assert.equal(
    validatePushSubscriptionEndpoint('https://db5p.notify.windows.com/w/?token=token123'),
    'https://db5p.notify.windows.com/w/?token=token123',
  );
});

test('validatePushSubscriptionKeys and validateNotificationPayload enforce validation boundaries', () => {
  // Invalid keys
  assert.throws(() => validatePushSubscriptionKeys(null), /keys must be an object/);
  assert.throws(() => validatePushSubscriptionKeys({ p256dh: '', auth: 'valid' }), /p256dh key must be a non-empty string/);
  assert.throws(() => validatePushSubscriptionKeys({ p256dh: 'short', auth: 'valid' }), /Invalid p256dh cryptographic key format/);

  // Valid keys
  const validKeys = validatePushSubscriptionKeys({
    p256dh: 'BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9t044YjsCfqWmqurCPTxJEoKsFeQDjdFs444D8wvGWzk9s',
    auth: 'tBHItJI5svbpez7KI4CCXg',
  });
  assert.equal(validKeys.auth, 'tBHItJI5svbpez7KI4CCXg');

  // Payload sanitization
  const cleanPayload = validateNotificationPayload({
    title: '  My Alert  ',
    body: '  Your site has finished building!  ',
    data: { url: '/projects/123' },
  });
  assert.equal(cleanPayload.title, 'My Alert');
  assert.equal(cleanPayload.body, 'Your site has finished building!');
  assert.equal(cleanPayload.data?.url, '/projects/123');

  // Relative url fallback on dangerous protocol
  const badUrlPayload = validateNotificationPayload({
    title: 'Test',
    body: 'Test',
    data: { url: 'javascript:alert(1)' },
  });
  assert.equal(badUrlPayload.data?.url, '/');
});

test('PushNotificationService registers, filters by user, and unregisters subscriptions', async () => {
  const service = new PushNotificationService();

  const sub1: WebPushSubscription = {
    endpoint: 'https://fcm.googleapis.com/fcm/send/sub1',
    keys: {
      p256dh: 'BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9t044YjsCfqWmqurCPTxJEoKsFeQDjdFs444D8wvGWzk9s',
      auth: 'tBHItJI5svbpez7KI4CCXg',
    },
  };

  const sub2: WebPushSubscription = {
    endpoint: 'https://fcm.googleapis.com/fcm/send/sub2',
    keys: {
      p256dh: 'BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZfIOCeSglVwJUqwt16h394z_zJ997B_f_n4wS8',
      auth: 'k9Jb2a5Fk83lsKx210',
    },
  };

  await service.addSubscription(sub1, 'user-alpha');
  await service.addSubscription(sub2, 'user-beta');

  const allSubs = await service.getSubscriptions();
  assert.equal(allSubs.length, 2);

  const alphaSubs = await service.getSubscriptions('user-alpha');
  assert.equal(alphaSubs.length, 1);
  assert.equal(alphaSubs[0].endpoint, sub1.endpoint);

  const betaSubs = await service.getSubscriptions('user-beta');
  assert.equal(betaSubs.length, 1);

  const removed = await service.removeSubscription(sub1.endpoint, 'user-alpha');
  assert.equal(removed, true);

  const remainingAlpha = await service.getSubscriptions('user-alpha');
  assert.equal(remainingAlpha.length, 0);

  const remainingAll = await service.getSubscriptions();
  assert.equal(remainingAll.length, 1);
});

test('Subscription persistence survives service restarts via database store', async () => {
  const sharedStore = new InMemoryAdminStore();

  // 1. Initial service instance registers subscription
  const service1 = new PushNotificationService({ store: sharedStore });
  const sub: WebPushSubscription = {
    endpoint: 'https://fcm.googleapis.com/fcm/send/persistent-sub-1',
    keys: {
      p256dh: 'BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9t044YjsCfqWmqurCPTxJEoKsFeQDjdFs444D8wvGWzk9s',
      auth: 'tBHItJI5svbpez7KI4CCXg',
    },
  };

  await service1.addSubscription(sub, 'user-persistent');
  const subs1 = await service1.getSubscriptions('user-persistent');
  assert.equal(subs1.length, 1);

  // 2. Fresh service instance (simulating server reboot with same store)
  const service2 = new PushNotificationService({ store: sharedStore });
  const subs2 = await service2.getSubscriptions('user-persistent');
  assert.equal(subs2.length, 1);
  assert.equal(subs2[0].endpoint, sub.endpoint);
  assert.equal(subs2[0].userId, 'user-persistent');

  // 3. User can delete subscription from new service instance
  const deleted = await service2.removeSubscription(sub.endpoint, 'user-persistent');
  assert.equal(deleted, true);

  const subsAfterDelete = await service2.getSubscriptions('user-persistent');
  assert.equal(subsAfterDelete.length, 0);
});

test('Subscription ownership checks prevent unauthorized users from modifying subscriptions', async () => {
  const store = new InMemoryAdminStore();
  const service = new PushNotificationService({ store });

  const subAlice: WebPushSubscription = {
    endpoint: 'https://fcm.googleapis.com/fcm/send/sub-alice-only',
    keys: {
      p256dh: 'BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9t044YjsCfqWmqurCPTxJEoKsFeQDjdFs444D8wvGWzk9s',
      auth: 'tBHItJI5svbpez7KI4CCXg',
    },
  };

  // Alice registers her endpoint
  await service.addSubscription(subAlice, 'user-alice');

  // Bob attempts to overwrite or re-register Alice's endpoint -> rejected with 403
  await assert.rejects(
    async () => {
      await service.addSubscription(subAlice, 'user-bob');
    },
    /registered to another account|belongs to another account/i,
  );

  // Bob attempts to unsubscribe Alice's endpoint -> rejected with 403
  await assert.rejects(
    async () => {
      await service.removeSubscription(subAlice.endpoint, 'user-bob');
    },
    /belongs to another account/i,
  );

  // Alice can cleanly unsubscribe her own endpoint
  const aliceRemoved = await service.removeSubscription(subAlice.endpoint, 'user-alice');
  assert.equal(aliceRemoved, true);
});

test('Expired subscription cleanup drops subscriptions past expirationTime', async () => {
  const store = new InMemoryAdminStore();
  const service = new PushNotificationService({ store });

  const pastExpiration = Date.now() - 60_000;
  const futureExpiration = Date.now() + 600_000;

  await service.addSubscription(
    {
      endpoint: 'https://fcm.googleapis.com/fcm/send/sub-expired',
      expirationTime: pastExpiration,
      keys: {
        p256dh: 'BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9t044YjsCfqWmqurCPTxJEoKsFeQDjdFs444D8wvGWzk9s',
        auth: 'tBHItJI5svbpez7KI4CCXg',
      },
    },
    'user-expiry',
  );

  await service.addSubscription(
    {
      endpoint: 'https://fcm.googleapis.com/fcm/send/sub-active',
      expirationTime: futureExpiration,
      keys: {
        p256dh: 'BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9t044YjsCfqWmqurCPTxJEoKsFeQDjdFs444D8wvGWzk9s',
        auth: 'tBHItJI5svbpez7KI4CCXg',
      },
    },
    'user-expiry',
  );

  const initialCount = (await service.getSubscriptions('user-expiry')).length;
  assert.equal(initialCount, 2);

  const cleaned = await service.cleanupExpiredSubscriptions();
  assert.equal(cleaned, 1);

  const remaining = await service.getSubscriptions('user-expiry');
  assert.equal(remaining.length, 1);
  assert.equal(remaining[0].endpoint, 'https://fcm.googleapis.com/fcm/send/sub-active');
});

test('Server notification endpoints enforce authentication, ownership, SSRF protection, and rate limits', async () => {
  const customStore = new InMemoryAdminStore();
  const customService = new PushNotificationService({ store: customStore });
  const app = createMistApp({
    notificationService: customService,
    verifyAuthHeader: async (header) => {
      if (header === 'Bearer alice-token') {
        return {
          userId: 'user-alice',
          uid: 'user-alice',
          email: 'alice@example.com',
          emailVerified: true,
          idToken: 'alice-token',
        };
      }
      if (header === 'Bearer bob-token') {
        return {
          userId: 'user-bob',
          uid: 'user-bob',
          email: 'bob@example.com',
          emailVerified: true,
          idToken: 'bob-token',
        };
      }
      throw new Error('Unauthorized');
    },
  });

  const server = http.createServer(app);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', () => resolve()));
  const port = (server.address() as AddressInfo).port;
  const baseUrl = `http://127.0.0.1:${port}`;

  try {
    // 1. GET /sw.js
    const swRes = await fetch(`${baseUrl}/sw.js`);
    assert.equal(swRes.status, 200);
    assert.equal(swRes.headers.get('service-worker-allowed'), '/');
    assert.ok(swRes.headers.get('content-type')?.includes('application/javascript'));
    const swText = await swRes.text();
    assert.ok(swText.includes('mist-notification'));

    // 2. GET /api/notifications/vapid-public-key
    const keyRes = await fetch(`${baseUrl}/api/notifications/vapid-public-key`);
    assert.equal(keyRes.status, 200);
    const keyJson = await keyRes.json();
    assert.ok(keyJson.publicKey);
    assert.ok(keyJson.subject);

    // 3. POST /api/notifications/subscribe - Anonymous request rejected with 401
    const subPayload = {
      subscription: {
        endpoint: 'https://updates.push.services.mozilla.com/wpush/v2/gAAAAAB_token123',
        keys: {
          p256dh: 'BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9t044YjsCfqWmqurCPTxJEoKsFeQDjdFs444D8wvGWzk9s',
          auth: 'tBHItJI5svbpez7KI4CCXg',
        },
      },
    };
    const subResAnon = await fetch(`${baseUrl}/api/notifications/subscribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(subPayload),
    });
    assert.equal(subResAnon.status, 401);

    // 4. POST /api/notifications/subscribe - SSRF attack with private IP rejected with 400
    const ssrfPayload = {
      subscription: {
        endpoint: 'https://169.254.169.254/latest/meta-data',
        keys: subPayload.subscription.keys,
      },
    };
    const ssrfRes = await fetch(`${baseUrl}/api/notifications/subscribe`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer alice-token',
      },
      body: JSON.stringify(ssrfPayload),
    });
    assert.equal(ssrfRes.status, 400);
    const ssrfJson = await ssrfRes.json();
    assert.match(ssrfJson.error, /cannot be an IP address/i);

    // 5. POST /api/notifications/subscribe - Arbitrary unapproved domain rejected with 400
    const evilDomainPayload = {
      subscription: {
        endpoint: 'https://attacker.evil.com/webhook',
        keys: subPayload.subscription.keys,
      },
    };
    const evilRes = await fetch(`${baseUrl}/api/notifications/subscribe`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer alice-token',
      },
      body: JSON.stringify(evilDomainPayload),
    });
    assert.equal(evilRes.status, 400);
    const evilJson = await evilRes.json();
    assert.match(evilJson.error, /not a recognized Web Push service provider/i);

    // 6. POST /api/notifications/subscribe - Alice registers valid subscription
    const aliceSubRes = await fetch(`${baseUrl}/api/notifications/subscribe`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer alice-token',
      },
      body: JSON.stringify(subPayload),
    });
    assert.equal(aliceSubRes.status, 200);
    const aliceSubs = await customService.getSubscriptions('user-alice');
    assert.equal(aliceSubs.length, 1);

    // 7. Ownership enforcement: Bob attempts to unsubscribe Alice's endpoint -> 403 Forbidden
    const bobUnsubRes = await fetch(`${baseUrl}/api/notifications/unsubscribe`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer bob-token',
      },
      body: JSON.stringify({ endpoint: subPayload.subscription.endpoint }),
    });
    assert.equal(bobUnsubRes.status, 403);
    const bobUnsubJson = await bobUnsubRes.json();
    assert.match(bobUnsubJson.error, /belongs to another account/i);

    // 8. Ownership enforcement: Bob attempts to register Alice's endpoint -> 403 Forbidden
    const bobSubRes = await fetch(`${baseUrl}/api/notifications/subscribe`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer bob-token',
      },
      body: JSON.stringify(subPayload),
    });
    assert.equal(bobSubRes.status, 403);

    // 9. POST /api/notifications/cleanup - cleans expired subscriptions
    const cleanupRes = await fetch(`${baseUrl}/api/notifications/cleanup`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer alice-token',
      },
    });
    assert.equal(cleanupRes.status, 200);
    const cleanupJson = await cleanupRes.json();
    assert.equal(cleanupJson.ok, true);

    // 10. POST /api/notifications/unsubscribe - Alice unsubscribes her own endpoint -> 200 OK
    const aliceUnsubRes = await fetch(`${baseUrl}/api/notifications/unsubscribe`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer alice-token',
      },
      body: JSON.stringify({ endpoint: subPayload.subscription.endpoint }),
    });
    assert.equal(aliceUnsubRes.status, 200);
    const remaining = await customService.getSubscriptions('user-alice');
    assert.equal(remaining.length, 0);
  } finally {
    server.close();
  }
});
