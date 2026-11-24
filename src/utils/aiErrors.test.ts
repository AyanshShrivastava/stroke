import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyModelError, redactSecrets } from './aiErrors';

test('classifyModelError classifies OpenRouter 402 credits/max_tokens failure as CREDITS_REQUIRED', () => {
  const incident = classifyModelError({
    status: 402,
    provider: 'custom',
    model: 'openai/gpt-4.1',
    message:
      'OpenRouter error (402): {"error":{"message":"This request requires more credits, or fewer max_tokens. You requested up to 65536 tokens, but can only afford 5000.","code":402,"metadata":{"limit_source":"openrouter_credits"}}}',
  });

  assert.equal(incident.code, 'CREDITS_REQUIRED');
  assert.equal(incident.title, 'openai/gpt-4.1 requires paid credits');
  assert.ok(incident.message.includes('5000 tokens'));
  assert.ok(incident.message.includes(':free'));
});

test('classifyModelError detects rate limit, outage, and auth errors accurately', () => {
  const rateLimit = classifyModelError({
    status: 429,
    provider: 'custom',
    model: 'gemini-2.5-flash',
    message: 'Resource exhausted, retry in 12s',
  });
  assert.equal(rateLimit.code, 'RATE_LIMIT');
  assert.equal(rateLimit.retryAfterSeconds, 12);

  const outage = classifyModelError({
    status: 503,
    provider: 'custom',
    model: 'nvidia/llama-3.3-nemotron-super-49b-v1:free',
    message: 'Service Unavailable',
  });
  assert.equal(outage.code, 'SERVER_OUTAGE');

  const auth = classifyModelError({
    status: 401,
    provider: 'custom',
    model: 'openai/gpt-4.1',
    message: 'Invalid API key sk-or-v1-1234567890abcdef123456',
  });
  assert.equal(auth.code, 'AUTH_ERROR');
  assert.ok(!auth.message.includes('sk-or-v1-1234567890abcdef123456'));
});

test('redactSecrets scrubs provider keys, Bearer tokens, session tokens, and query secrets', () => {
  const raw =
    'Authorization: Bearer sk-or-v1-secret1234567890 failed with gsk_abcdefghijklmnopqrstuvwxyz and AIzaSyDummySecretKey1234567890 and mist_sess_abcdef1234567890 at https://example.com?key=supersecret123';
  const cleaned = redactSecrets(raw);
  assert.ok(!cleaned.includes('sk-or-v1-secret1234567890'));
  assert.ok(!cleaned.includes('gsk_abcdefghijklmnopqrstuvwxyz'));
  assert.ok(!cleaned.includes('AIzaSyDummySecretKey1234567890'));
  assert.ok(!cleaned.includes('mist_sess_abcdef1234567890'));
  assert.ok(!cleaned.includes('supersecret123'));
  assert.ok(cleaned.includes('[REDACTED]'));
});

