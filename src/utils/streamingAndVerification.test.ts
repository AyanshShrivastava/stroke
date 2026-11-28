import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import {
  createIncrementalSseParser,
  consumeOpenAiCompatibleSseStream,
  executeDirectGenerate,
} from './directClientAi';
import {
  createMistApp,
  verifyFinalProjectState,
  isVerificationValidForFiles,
} from './mistServerApp';
import type { ProjectFile } from '../types/mist';
import type { PushNotificationService } from './notificationService';

function makeChunkedStream(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) {
        controller.enqueue(c);
      }
      controller.close();
    },
  });
}

test('createIncrementalSseParser handles CRLF split across chunks, multi-event chunks, multi-line data, and EOF flush', () => {
  const events: string[] = [];
  const parser = createIncrementalSseParser((ev) => events.push(ev.data));

  // Chunk 1 ends with \r, Chunk 2 starts with \n; includes comment + multi-line data + multiple events
  parser.push('data: {"a":1}\r');
  parser.push('\n\r\n: keepalive comment\r\ndata: {"b":\n');
  parser.push('data: 2}\n\ndata: {"c":3}\ndata: {"d":4}\n');
  // Final line has no trailing newline (must flush on finish)
  parser.push('data: {"e":5}');
  parser.finish();

  assert.deepEqual(events, [
    '{"a":1}',
    '{"b":\n2}',
    '{"c":3}',
    '{"d":4}',
    '{"e":5}',
  ]);
});

test('consumeOpenAiCompatibleSseStream reconstructs content cleanly across EVERY possible 1-byte split boundary', async () => {
  const payload =
    'data: {"choices":[{"delta":{"content":"Hello "}}]}\r\n\r\n' +
    'data: {"choices":[{"delta":{"content":"Mist ✨"}}]}\n\n' +
    'data: {"choices":[{"delta":{"content":"!"}}]}\n' +
    'data: [DONE]';

  const bytes = new TextEncoder().encode(payload);

  // Split into 1-byte chunks so every single byte boundary (UTF-8 multi-byte, data:, JSON, \r, \n, [DONE]) is tested
  const oneByteChunks = Array.from(bytes, (b) => new Uint8Array([b]));
  const result = await consumeOpenAiCompatibleSseStream({
    body: makeChunkedStream(oneByteChunks),
  });

  assert.equal(result, 'Hello Mist ✨!');
});

test('consumeOpenAiCompatibleSseStream handles stream cancellation and upstream errors cleanly', async () => {
  const controller = new AbortController();
  let cancelled = false;

  const stream = new ReadableStream<Uint8Array>({
    start(ctrl) {
      ctrl.enqueue(new TextEncoder().encode('data: {"choices":[{"delta":{"content":"Part1"}}]}\n\n'));
    },
    cancel() {
      cancelled = true;
    },
  });

  const promise = consumeOpenAiCompatibleSseStream({
    body: stream,
    signal: controller.signal,
  });

  setTimeout(() => controller.abort(), 15);
  await assert.rejects(promise, /Abort/);
  assert.equal(cancelled, true);
});

test('executeDirectGenerate preserves complete JSON files when SSE events are split mid-line across chunks', async () => {
  const generatedJson = JSON.stringify({
    projectName: 'Boundary Safe App',
    description: 'Verified SSE boundary reconstruction',
    summary: 'Complete app',
    files: [
      {
        path: 'src/App.tsx',
        language: 'tsx',
        content: 'export default function App() { return <div>Boundary Safe</div>; }',
      },
    ],
  });

  const sseFull =
    `data: ${JSON.stringify({ choices: [{ delta: { content: generatedJson.slice(0, 45) } }] })}\r\n\r\n` +
    `data: ${JSON.stringify({ choices: [{ delta: { content: generatedJson.slice(45) } }] })}\n` +
    `data: [DONE]`;

  const bytes = new TextEncoder().encode(sseFull);
  // Split at awkward odd-byte intervals (7 bytes per chunk) across headers/JSON/CRLF
  const chunks: Uint8Array[] = [];
  for (let i = 0; i < bytes.length; i += 7) {
    chunks.push(bytes.slice(i, i + 7));
  }

  const fakeFetch: typeof fetch = async () =>
    new Response(makeChunkedStream(chunks), {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    });

  const result = await executeDirectGenerate({
    prompt: 'Build boundary safe app',
    config: {
      provider: 'gemini',
      name: 'Gemini',
      model: 'gemini-2.5-flash',
      apiKey: 'AIza-mock-test-key-1234',
      baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    },
    fetchImpl: fakeFetch,
  });

  assert.equal(result.projectName, 'Boundary Safe App');
  assert.ok(result.files.some((f) => f.path === 'src/App.tsx' && f.content.includes('Boundary Safe')));
  assert.ok(result.files.some((f) => f.path === 'src/index.css'));
});

test('verifyFinalProjectState invalidates prior verification when files (such as src/index.css or src/App.tsx) change', async () => {
  const initialFiles: ProjectFile[] = [
    {
      id: 'f1',
      path: 'src/App.tsx',
      language: 'tsx',
      content: 'export default function App() { return <main>Valid</main>; }',
    },
  ];

  const v1 = await verifyFinalProjectState({ files: initialFiles, title: 'Test App' });
  assert.equal(v1.verified, true);
  assert.equal(v1.buildOk, true);
  assert.ok(v1.warnings.some((w) => w.includes('src/index.css')));
  assert.equal(isVerificationValidForFiles(v1, initialFiles), true);

  // Mutate project by adding src/index.css after v1
  const withCss: ProjectFile[] = [
    ...initialFiles,
    { id: 'f2', path: 'src/index.css', language: 'css', content: '@import "tailwindcss";\n' },
  ];
  assert.equal(isVerificationValidForFiles(v1, withCss), false);

  const v2 = await verifyFinalProjectState({
    files: withCss,
    title: 'Test App',
    priorVerification: v1,
  });
  assert.equal(v2.verified, true);
  assert.deepEqual(v2.warnings, []);
  assert.equal(isVerificationValidForFiles(v2, withCss), true);

  // Break src/App.tsx after v2 -> previous verification invalidated and re-verify fails honestly
  const brokenFiles: ProjectFile[] = [
    { id: 'f1', path: 'src/App.tsx', language: 'tsx', content: 'export default function App( { return <div' },
    withCss[1]!,
  ];
  assert.equal(isVerificationValidForFiles(v2, brokenFiles), false);

  const v3 = await verifyFinalProjectState({
    files: brokenFiles,
    title: 'Test App',
    priorVerification: v2,
  });
  assert.equal(v3.verified, false);
  assert.equal(v3.buildOk, false);
  assert.ok(v3.bundleError && v3.bundleError.length > 0);
});

test('POST /api/ai/generate runs verification after post-processing and never sends a verified notification for a broken build', async () => {
  const sentNotifications: Array<{ title: string; body: string }> = [];
  const mockNotifService = {
    sendNotificationToUser: async (_uid: string, payload: { title: string; body: string }) => {
      sentNotifications.push({ title: payload.title, body: payload.body });
      return { sent: 1, failed: 0, expiredCleaned: 0 };
    },
  } as unknown as PushNotificationService;

  const brokenPayload = JSON.stringify({
    projectName: 'Broken Site',
    description: 'Broken TSX',
    summary: 'Broken app',
    files: [
      {
        path: 'src/App.tsx',
        language: 'tsx',
        content: 'export default function App() { return <div><<<BROKEN_JSX',
      },
    ],
  });

  const app = createMistApp({
    skipDnsLookup: true,
    verifyAuthHeader: async () => ({
      userId: 'user_test_1',
      uid: 'user_test_1',
      email: 'dev@example.com',
      emailVerified: true,
    }),
    notificationService: mockNotifService,
    aiFetchImpl: (async () =>
      new Response(
        JSON.stringify({ choices: [{ message: { content: brokenPayload } }] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      )) as typeof fetch,
  });

  const server = http.createServer(app);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const addr = server.address() as AddressInfo;

  try {
    const resp = await fetch(`http://127.0.0.1:${addr.port}/api/ai/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer mock-token',
      },
      body: JSON.stringify({
        prompt: 'Build broken site',
        providerConfig: {
          provider: 'custom',
          name: 'Gemini (BYOK)',
          baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
          model: 'gemini-2.5-flash',
          apiKey: 'AIza-mock-user-key',
        },
      }),
    });
    assert.equal(resp.status, 200);
    const json = (await resp.json()) as {
      files: ProjectFile[];
      verification?: { verified: boolean; buildOk: boolean; bundleError?: string };
    };
    assert.ok(json.files.some((f) => f.path === 'src/index.css'));
    assert.equal(json.verification?.verified, false);
    assert.equal(json.verification?.buildOk, false);
    assert.ok(json.verification?.bundleError);

    await new Promise((r) => setTimeout(r, 25));
    assert.equal(sentNotifications.length, 1);
    assert.match(sentNotifications[0]!.title, /Errors/i);
    assert.doesNotMatch(sentNotifications[0]!.title, /Verified/i);
    assert.doesNotMatch(sentNotifications[0]!.body, /generated successfully/i);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((err) => (err ? reject(err) : resolve())));
  }
});

test('POST /api/ai/generate automatically detects mist-missing:@react-three/fiber and self-repairs to valid pure three.js', async () => {
  const brokenR3fPayload = JSON.stringify({
    projectName: 'Neon Strike 3D',
    description: '3D game',
    summary: 'Initial R3F attempt',
    files: [
      {
        path: 'src/App.tsx',
        language: 'tsx',
        content: `import React from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { PerspectiveCamera, Stars } from '@react-three/drei';
export default function App() { return <Canvas><PerspectiveCamera /><Stars /></Canvas>; }`,
      },
    ],
  });

  const repairedThreePayload = JSON.stringify({
    summary: 'Rewrote 3D scene using pure three.js',
    files: [
      {
        path: 'src/App.tsx',
        language: 'tsx',
        content: `import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';
export default function App() {
  const mountRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const scene = new THREE.Scene();
    void scene;
  }, []);
  return <div ref={mountRef} className="w-full h-screen bg-black" />;
}`,
      },
      {
        path: 'src/index.css',
        language: 'css',
        content: '@import "tailwindcss";\n',
      },
    ],
  });

  let modelCallCount = 0;
  let repairPromptSawMissingModule = false;

  const app = createMistApp({
    skipDnsLookup: true,
    verifyAuthHeader: async () => ({
      userId: 'user_test_2',
      uid: 'user_test_2',
      email: 'dev@example.com',
      emailVerified: true,
    }),
    aiFetchImpl: (async (_url, init) => {
      modelCallCount += 1;
      const bodyStr = String(init?.body || '');
      if (modelCallCount === 1) {
        return new Response(
          JSON.stringify({ choices: [{ message: { content: brokenR3fPayload } }] }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (bodyStr.includes('@react-three/fiber') || bodyStr.includes('mist-missing')) {
        repairPromptSawMissingModule = true;
      }
      return new Response(
        JSON.stringify({ choices: [{ message: { content: repairedThreePayload } }] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }) as typeof fetch,
  });

  const server = http.createServer(app);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const addr = server.address() as AddressInfo;

  try {
    const resp = await fetch(`http://127.0.0.1:${addr.port}/api/ai/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer mock-token',
      },
      body: JSON.stringify({
        prompt: 'Build Neon Strike 3D game',
        providerConfig: {
          provider: 'custom',
          name: 'Gemini (BYOK)',
          baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
          model: 'gemini-2.5-flash',
          apiKey: 'AIza-mock-user-key',
        },
      }),
    });
    assert.equal(resp.status, 200);
    const json = (await resp.json()) as {
      repairAttempts?: number;
      verification?: { verified: boolean; buildOk: boolean; bundleError?: string };
      files: ProjectFile[];
    };
    assert.equal(modelCallCount, 2);
    assert.equal(repairPromptSawMissingModule, true);
    assert.equal(json.repairAttempts, 1);
    assert.equal(json.verification?.verified, true);
    assert.equal(json.verification?.buildOk, true);
    assert.ok(json.files.some((f) => f.path === 'src/App.tsx' && f.content.includes("from 'three'")));
  } finally {
    await new Promise<void>((resolve, reject) => server.close((err) => (err ? reject(err) : resolve())));
  }
});

test('POST /api/ai/refine verifies partial refined files against full project and auto-repairs broken external imports', async () => {
  let callCount = 0;
  let repairSawPartialContextAndMissingPkg = false;
  const app = createMistApp({
    skipDnsLookup: true,
    verifyAuthHeader: async () => ({
      userId: 'user-a',
      uid: 'user-a',
      email: 'alice@example.com',
      emailVerified: true,
      idToken: 'token-a',
    }),
    aiFetchImpl: async (_url, init) => {
      callCount += 1;
      const bodyStr = typeof init?.body === 'string' ? init.body : '';
      if (callCount === 1) {
        return new Response(
          JSON.stringify({
            choices: [
              {
                message: {
                  content: JSON.stringify({
                    summary: 'Added Scene component',
                    files: [
                      {
                        path: 'src/components/Scene.tsx',
                        language: 'tsx',
                        content: `import React from 'react';
import gsap from 'gsap';
export function Scene() {
  void gsap;
  return <div>Scene</div>;
}`,
                      },
                    ],
                  }),
                },
              },
            ],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      repairSawPartialContextAndMissingPkg =
        bodyStr.includes('gsap') && bodyStr.includes('src/App.tsx');
      return new Response(
        JSON.stringify({
          choices: [
            {
              message: {
                content: JSON.stringify({
                  summary: 'Replaced gsap with CSS transition',
                  files: [
                    {
                      path: 'src/components/Scene.tsx',
                      language: 'tsx',
                      content: `import React from 'react';
export function Scene() {
  return <div className="transition-all">Scene Fixed</div>;
}`,
                    },
                  ],
                }),
              },
            },
          ],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    },
  });

  const server = http.createServer(app);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', () => resolve()));
  const addr = server.address();
  assert.ok(addr && typeof addr !== 'string');
  const baseUrl = `http://127.0.0.1:${addr.port}`;

  try {
    const resp = await fetch(`${baseUrl}/api/ai/refine`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer mock-token',
      },
      body: JSON.stringify({
        instruction: 'Update Scene animation',
        files: [
          {
            id: 'f1',
            path: 'src/App.tsx',
            language: 'tsx',
            content: `import React from 'react';
import { Scene } from './components/Scene';
export default function App() {
  return <Scene />;
}`,
          },
          {
            id: 'f2',
            path: 'src/components/Scene.tsx',
            language: 'tsx',
            content: `import React from 'react';
export function Scene() {
  return <div>Old Scene</div>;
}`,
          },
          {
            id: 'f3',
            path: 'src/index.css',
            language: 'css',
            content: '@import "tailwindcss";\n',
          },
        ],
        providerConfig: {
          provider: 'custom',
          name: 'Gemini (BYOK)',
          baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
          model: 'gemini-2.5-flash',
          apiKey: 'AIza-mock-user-key',
        },
      }),
    });
    assert.equal(resp.status, 200);
    const json = (await resp.json()) as {
      repairAttempts?: number;
      verification?: { verified: boolean; buildOk: boolean; bundleError?: string };
      files: Array<{ path: string; content: string }>;
    };
    assert.equal(callCount, 2);
    assert.equal(repairSawPartialContextAndMissingPkg, true);
    assert.equal(json.repairAttempts, 1);
    assert.equal(json.verification?.verified, true);
    assert.equal(json.verification?.buildOk, true);
    assert.ok(
      json.files.some(
        (f) => f.path === 'src/components/Scene.tsx' && !f.content.includes("'gsap'"),
      ),
    );
  } finally {
    await new Promise<void>((resolve, reject) => server.close((err) => (err ? reject(err) : resolve())));
  }
});
