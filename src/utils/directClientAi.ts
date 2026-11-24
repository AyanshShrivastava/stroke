/**
 * Direct Client-to-Gemini BYOK AI Executor.
 * Bypasses the Mist server completely so browser streams directly from Google Gemini / BYOK gateways.
 * Zero server CPU/memory/bandwidth used for LLM streaming.
 */

import type { AiProviderConfig, ProjectFile, WebSearchOutcome } from '../types/mist';
import { normalizeProjectFilePath, inferLanguageFromPath } from './projectOps';

export const CLIENT_SYSTEM_GENERATOR_PROMPT = `You are Mist, a senior product designer, interactive game developer, and React + TypeScript + Tailwind CSS + Three.js engineer.
Generate clean, cohesive, responsive, fully playable/interactive web apps with strong contrast, crisp typography, mobile support, and zero broken links.

LIGHTWEIGHT & HIGH-RELIABILITY ARCHITECTURE RULES:
- Structure each project cleanly into 2 to 5 cohesive files max (e.g., src/App.tsx + 1-3 well-defined files in src/components/* + src/index.css).
- "src/App.tsx" MUST be the VERY FIRST file in the "files" array and MUST default-export App (export default function App()).
- Verify that EVERY local import (e.g. import Header from './components/Header') matches an actual file you return AND that the exported symbol exists identically.
- Write complete, rich, production-grade TypeScript code — NEVER use "// TODO", "...rest of code", or placeholder cards.
- Build genuine mobile-first + desktop responsive layouts (sm:, md:, lg: grids/flex, touch-friendly >=40px tap targets).
- Use React 19, TypeScript (.tsx), and Tailwind CSS utility classes.
- Allowed imports: 'react', 'react-dom/client', 'lucide-react', 'three', 'three/addons/*' (e.g., OrbitControls, RoomEnvironment), and local relative imports like './components/Navbar'.
- Ensure src/index.css starts with @import "tailwindcss";.
- NEVER use <a href="/..."> links on interactive buttons (such as "Play Game", "Start", "Restart") — ALWAYS use <button type="button" onClick={...}>.

Return valid JSON in this exact structure:
{
  "projectName": "Short Title",
  "description": "One sentence summary",
  "summary": "Key highlights of what was created",
  "files": [
    { "path": "src/App.tsx", "language": "tsx", "content": "..." },
    { "path": "src/index.css", "language": "css", "content": "@import \\"tailwindcss\\";\\n" }
  ]
}`;

export function canUseDirectClient(config?: AiProviderConfig): boolean {
  if (!config || !config.apiKey?.trim()) return false;
  const key = config.apiKey.trim();
  const base = (config.baseUrl || '').toLowerCase();
  // Gemini BYOK (AIza key or Google endpoint)
  if (key.startsWith('AIza') || base.includes('generativelanguage.googleapis.com') || config.provider === 'gemini') {
    return true;
  }
  // OpenRouter or Groq with client CORS support
  if (base.includes('openrouter.ai') || base.includes('groq.com')) {
    return true;
  }
  return false;
}

export function resolveDirectEndpoint(config: AiProviderConfig): { url: string; headers: Record<string, string> } {
  const apiKey = (config.apiKey || '').trim();
  const base = (config.baseUrl || '').trim().replace(/\/+$/, '');

  if (apiKey.startsWith('AIza') || base.includes('generativelanguage.googleapis.com') || config.provider === 'gemini') {
    const cleanBase = base || 'https://generativelanguage.googleapis.com/v1beta/openai';
    const endpoint = cleanBase.endsWith('/chat/completions') ? cleanBase : `${cleanBase}/chat/completions`;
    return {
      url: endpoint,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
    };
  }

  const endpoint = base.endsWith('/chat/completions') ? base : `${base}/chat/completions`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${apiKey}`,
  };

  if (endpoint.includes('openrouter.ai')) {
    headers['HTTP-Referer'] = window.location.origin;
    headers['X-Title'] = 'Mist Website Builder';
  }

  return { url: endpoint, headers };
}

export interface DirectStreamProgressEvent {
  type: 'phase' | 'file_start' | 'file_done' | 'progress';
  phase?: string;
  activeFile?: string;
  completedFiles?: string[];
  chars?: number;
}

export interface DirectGeneratedProject {
  projectName: string;
  description: string;
  summary: string;
  searchOutcome?: WebSearchOutcome;
  files: Array<{ path: string; language?: ProjectFile['language']; content: string }>;
}

function parseStreamJsonFiles(raw: string): DirectGeneratedProject {
  const trimmed = raw.trim();
  const fenceMatch = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fenceMatch ? fenceMatch[1].trim() : trimmed;

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(candidate);
  } catch {
    const firstBrace = candidate.indexOf('{');
    const lastBrace = candidate.lastIndexOf('}');
    if (firstBrace !== -1 && lastBrace > firstBrace) {
      parsed = JSON.parse(candidate.slice(firstBrace, lastBrace + 1));
    } else {
      throw new Error('Could not parse JSON files from AI stream.');
    }
  }

  const rawFiles = Array.isArray(parsed.files) ? (parsed.files as Array<{ path?: string; content?: string }>) : [];
  const files: Array<{ path: string; language?: ProjectFile['language']; content: string }> = [];

  for (const f of rawFiles) {
    if (f.path && typeof f.content === 'string') {
      const cleanPath = normalizeProjectFilePath(f.path);
      files.push({
        path: cleanPath,
        language: inferLanguageFromPath(cleanPath),
        content: f.content,
      });
    }
  }

  // Ensure index.css exists
  if (!files.some((f) => f.path.toLowerCase() === 'src/index.css')) {
    files.push({
      path: 'src/index.css',
      language: 'css',
      content: '@import "tailwindcss";\n',
    });
  }

  return {
    projectName: typeof parsed.projectName === 'string' ? parsed.projectName : 'Generated Website',
    description: typeof parsed.description === 'string' ? parsed.description : '',
    summary: typeof parsed.summary === 'string' ? parsed.summary : 'Generated application files.',
    files,
  };
}

export async function executeDirectGenerate(options: {
  prompt: string;
  config: AiProviderConfig;
  signal?: AbortSignal;
  onProgress?: (event: DirectStreamProgressEvent) => void;
}): Promise<DirectGeneratedProject> {
  const { prompt, config, signal, onProgress } = options;
  const { url, headers } = resolveDirectEndpoint(config);

  onProgress?.({
    type: 'phase',
    phase: `Direct client connection to ${config.name || 'Gemini'} (${config.model})...`,
    chars: 0,
  });

  const userMessage = `Build a complete React + TypeScript + Tailwind CSS web app for this request:
"${prompt.trim()}"

Make sure src/App.tsx is the default export and first file. Return only valid JSON.`;

  const payload = {
    model: config.model || 'gemini-2.5-flash',
    messages: [
      { role: 'system', content: CLIENT_SYSTEM_GENERATOR_PROMPT },
      { role: 'user', content: userMessage },
    ],
    temperature: 0.7,
    stream: true,
  };

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    const message =
      (errorData && errorData.error && errorData.error.message) ||
      `Direct API error (${response.status}): ${response.statusText}`;
    throw new Error(message);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Response body is not readable.');
  }

  const decoder = new TextDecoder('utf-8');
  let accumulated = '';
  let seenPaths: string[] = [];

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value, { stream: true });
    const lines = chunk.split('\n');

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || !trimmed.startsWith('data:')) continue;
      const dataStr = trimmed.slice('data:'.length).trim();
      if (dataStr === '[DONE]') continue;

      try {
        const parsedChunk = JSON.parse(dataStr);
        const delta = parsedChunk.choices?.[0]?.delta?.content || '';
        if (delta) {
          accumulated += delta;

          // Track newly discovered files in the stream
          const pathMatches = Array.from(accumulated.matchAll(/"path"\s*:\s*"([^"]+)"/g));
          const currentPaths = pathMatches.map((m) => normalizeProjectFilePath(m[1]));
          const newPaths = currentPaths.filter((p) => !seenPaths.includes(p));

          if (newPaths.length > 0) {
            seenPaths = currentPaths;
            const latest = newPaths[newPaths.length - 1];
            onProgress?.({
              type: 'file_start',
              activeFile: latest,
              completedFiles: seenPaths.slice(0, -1),
              chars: accumulated.length,
            });
          } else {
            onProgress?.({
              type: 'progress',
              activeFile: seenPaths[seenPaths.length - 1],
              completedFiles: seenPaths,
              chars: accumulated.length,
            });
          }
        }
      } catch {
        // Partial SSE chunk, keep buffer
      }
    }
  }

  onProgress?.({
    type: 'phase',
    phase: 'Validating generated files...',
    completedFiles: seenPaths,
    chars: accumulated.length,
  });

  return parseStreamJsonFiles(accumulated);
}
