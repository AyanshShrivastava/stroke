import type {
  FileLanguage,
  MistProject,
  ProjectFile,
  VisualElementPatch,
} from '../types/mist';

export function createSafeId(prefix = 'id'): string {
  const cleanPrefix = prefix.replace(/[^a-zA-Z0-9_-]/g, '') || 'id';
  const rand = Math.random().toString(36).slice(2, 10);
  const ts = Date.now().toString(36);
  return `${cleanPrefix}_${ts}_${rand}`;
}

export function sanitizeSlug(input: string): string {
  const normalized = input
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64);
  if (normalized.length < 2) {
    return `mist-site-${Math.random().toString(36).slice(2, 6)}`;
  }
  return normalized;
}

const SLUG_STOP_WORDS = new Set([
  'a',
  'an',
  'the',
  'and',
  'for',
  'with',
  'website',
  'app',
  'application',
  'platform',
  'builder',
  'page',
]);

export function suggestShortSlug(input: string, maxLen = 24): string {
  const tokens = input
    .toLowerCase()
    .replace(/[^a-z0-9\s-]+/g, ' ')
    .split(/[\s-]+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0 && !SLUG_STOP_WORDS.has(t));

  if (tokens.length === 0) {
    return sanitizeSlug(input).slice(0, maxLen).replace(/-+$/g, '') || sanitizeSlug(input);
  }

  let acc = '';
  for (const token of tokens) {
    const candidate = acc ? `${acc}-${token}` : token;
    if (candidate.length <= maxLen) {
      acc = candidate;
    } else if (!acc) {
      acc = token.slice(0, maxLen);
      break;
    } else {
      break;
    }
  }
  const cleaned = acc.replace(/^-+|-+$/g, '');
  return cleaned.length >= 2 ? cleaned : sanitizeSlug(input).slice(0, maxLen);
}

export function maskApiKey(apiKey?: string): string {
  const trimmed = (apiKey || '').trim();
  if (!trimmed) return '';
  if (trimmed.length <= 6) return '••••••';
  if (trimmed.length <= 10) return `•••${trimmed.slice(-3)}`;
  return `${trimmed.slice(0, 4)}••••${trimmed.slice(-4)}`;
}

export function inferLanguageFromPath(filePath: string): FileLanguage {
  if (filePath.endsWith('.tsx')) return 'tsx';
  if (filePath.endsWith('.ts')) return 'ts';
  if (filePath.endsWith('.css')) return 'css';
  if (filePath.endsWith('.html')) return 'html';
  return 'json';
}

export function duplicateProjectData(project: MistProject): MistProject {
  const now = new Date().toISOString();
  const baseName = project.name.replace(/\s*\(Copy\)$/i, '');
  return {
    ...project,
    id: createSafeId('proj'),
    name: `${baseName} (Copy)`.slice(0, 120),
    publishedSlug: undefined,
    isPublished: false,
    createdAt: now,
    updatedAt: now,
    files: project.files.map((file) => ({
      ...file,
      id: createSafeId('file'),
    })),
    chatHistory: project.chatHistory.map((msg) => ({ ...msg })),
  };
}

export function normalizeProjectFilePath(rawPath: string): string {
  const cleaned = rawPath
    .trim()
    .replace(/\\/g, '/')
    .replace(/^(\.\/|\/)+/, '')
    .replace(/\/{2,}/g, '/');
  if (cleaned.toLowerCase() === 'src/app.tsx') {
    return 'src/App.tsx';
  }
  if (cleaned.toLowerCase() === 'src/main.tsx') {
    return 'src/main.tsx';
  }
  if (cleaned.toLowerCase() === 'src/index.css') {
    return 'src/index.css';
  }
  return cleaned;
}

export function resolveAppEntryPath(files: Array<Pick<ProjectFile, 'path' | 'content'>>): string | null {
  const normalized = files.map((f) => ({
    raw: f.path,
    clean: normalizeProjectFilePath(f.path),
    lower: normalizeProjectFilePath(f.path).toLowerCase(),
    content: f.content || '',
  }));

  const preferredOrder = [
    'src/app.tsx',
    'src/app.jsx',
    'app.tsx',
    'app.jsx',
    'src/pages/home.tsx',
    'src/app/page.tsx',
    'app/page.tsx',
    'src/home.tsx',
    'src/page.tsx',
  ];

  for (const target of preferredOrder) {
    const match = normalized.find((f) => f.lower === target);
    if (match) return match.clean;
  }

  // Fallback: prefer non-component .tsx/.jsx modules (excluding main.tsx) that export a component
  const nonComponentMatch = normalized.find(
    (f) =>
      (f.lower.endsWith('.tsx') || f.lower.endsWith('.jsx')) &&
      f.lower !== 'src/main.tsx' &&
      f.lower !== 'main.tsx' &&
      !f.lower.includes('/components/') &&
      (/export\s+default\s+/.test(f.content) || /export\s+(?:function|const)\s+App\b/.test(f.content)),
  );
  if (nonComponentMatch) return nonComponentMatch.clean;

  const componentMatch = normalized.find(
    (f) =>
      (f.lower.endsWith('.tsx') || f.lower.endsWith('.jsx')) &&
      f.lower !== 'src/main.tsx' &&
      f.lower !== 'main.tsx' &&
      (/export\s+default\s+/.test(f.content) || /export\s+(?:function|const)\s+App\b/.test(f.content)),
  );
  if (componentMatch) return componentMatch.clean;

  const anyTsx = normalized.find(
    (f) =>
      (f.lower.endsWith('.tsx') || f.lower.endsWith('.jsx')) &&
      f.lower !== 'src/main.tsx' &&
      f.lower !== 'main.tsx',
  );
  return anyTsx ? anyTsx.clean : null;
}

export function mergeProjectFiles(
  existingFiles: ProjectFile[],
  incomingFiles: Array<{ path: string; language?: FileLanguage; content: string }>,
): ProjectFile[] {
  const byPath = new Map<string, ProjectFile>();
  for (const file of existingFiles) {
    const cleanExisting = normalizeProjectFilePath(file.path);
    byPath.set(cleanExisting, { ...file, path: cleanExisting });
  }
  for (const item of incomingFiles) {
    const cleanPath = normalizeProjectFilePath(item.path);
    const existing = byPath.get(cleanPath);
    if (existing) {
      byPath.set(cleanPath, {
        ...existing,
        language: item.language ?? existing.language,
        content: item.content,
      });
    } else {
      byPath.set(cleanPath, {
        id: createSafeId('file'),
        path: cleanPath,
        language: item.language ?? inferLanguageFromPath(cleanPath),
        content: item.content,
      });
    }
  }
  return Array.from(byPath.values());
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function upsertOverrideCssBlock(
  cssContent: string,
  mistId: string,
  declarations: string[],
): string {
  const startMarker = `/* mist-override:${mistId}:start */`;
  const endMarker = `/* mist-override:${mistId}:end */`;
  const blockRegex = new RegExp(
    `${escapeRegExp(startMarker)}[\\s\\S]*?${escapeRegExp(endMarker)}\\n?`,
    'g',
  );
  const cleaned = cssContent.replace(blockRegex, '').trim();
  if (declarations.length === 0) {
    return cleaned ? `${cleaned}\n` : '';
  }
  const block = [
    startMarker,
    `[data-mist-id="${mistId}"] {`,
    ...declarations.map((line) => `  ${line}`),
    `}`,
    endMarker,
  ].join('\n');
  return cleaned ? `${cleaned}\n\n${block}\n` : `${block}\n`;
}

export function applyVisualPatchToFiles(
  files: ProjectFile[],
  patch: VisualElementPatch,
): ProjectFile[] {
  let nextFiles = files.map((file) => ({ ...file }));

  // 1. Update matching text literal in TSX/HTML files when unambiguous
  if (
    typeof patch.newText === 'string' &&
    typeof patch.originalText === 'string' &&
    patch.originalText.trim().length > 0 &&
    patch.newText !== patch.originalText
  ) {
    const target = patch.originalText.trim();
    const replacement = patch.newText;
    let replacedOnce = false;
    nextFiles = nextFiles.map((file) => {
      if (replacedOnce || (file.language !== 'tsx' && file.language !== 'html')) {
        return file;
      }
      const jsxTextPattern = new RegExp(`(>\\s*)${escapeRegExp(target)}(\\s*<)`);
      if (jsxTextPattern.test(file.content)) {
        replacedOnce = true;
        return {
          ...file,
          content: file.content.replace(jsxTextPattern, `$1${replacement}$2`),
        };
      }
      if (file.content.includes(target)) {
        replacedOnce = true;
        return {
          ...file,
          content: file.content.replace(target, replacement),
        };
      }
      return file;
    });
  }

  // 2. Persist visual style overrides into src/styles/mist-overrides.css
  const declarations: string[] = [];
  if (patch.deleted) {
    declarations.push('display: none !important;');
  } else if (patch.styles) {
    const s = patch.styles;
    if (s.color) declarations.push(`color: ${s.color} !important;`);
    if (s.backgroundColor) declarations.push(`background-color: ${s.backgroundColor} !important;`);
    if (s.fontSize) declarations.push(`font-size: ${s.fontSize} !important;`);
    if (s.fontWeight) declarations.push(`font-weight: ${s.fontWeight} !important;`);
    if (s.paddingTop) declarations.push(`padding-top: ${s.paddingTop} !important;`);
    if (s.paddingBottom) declarations.push(`padding-bottom: ${s.paddingBottom} !important;`);
    if (s.paddingLeft) declarations.push(`padding-left: ${s.paddingLeft} !important;`);
    if (s.paddingRight) declarations.push(`padding-right: ${s.paddingRight} !important;`);
    if (s.borderRadius) declarations.push(`border-radius: ${s.borderRadius} !important;`);
    if (s.textAlign) declarations.push(`text-align: ${s.textAlign} !important;`);
  }

  if (patch.deleted || (patch.styles && Object.keys(patch.styles).length > 0)) {
    const overridePath = 'src/styles/mist-overrides.css';
    const existingOverride = nextFiles.find((f) => f.path === overridePath);
    const updatedCss = upsertOverrideCssBlock(
      existingOverride?.content ?? '',
      patch.mistId,
      declarations,
    );
    if (existingOverride) {
      nextFiles = nextFiles.map((f) =>
        f.path === overridePath ? { ...f, content: updatedCss } : f,
      );
    } else {
      nextFiles.push({
        id: createSafeId('file'),
        path: overridePath,
        language: 'css',
        content: updatedCss,
      });
    }
  }

  return nextFiles;
}

export function applyDeterministicRefinement(
  files: ProjectFile[],
  instruction: string,
): { files: ProjectFile[]; summary: string; changedFiles: string[] } {
  const lower = instruction.toLowerCase();
  const changed = new Set<string>();
  let summary = '';

  let nextFiles = files.map((file) => ({ ...file }));

  if (lower.includes('navbar') && (lower.includes('smaller') || lower.includes('compact') || lower.includes('shorter'))) {
    nextFiles = nextFiles.map((file) => {
      if (file.path.includes('Navbar') || file.content.includes('<header')) {
        const updated = file.content
          .replace(/\bpy-6\b/g, 'py-2.5')
          .replace(/\bpy-5\b/g, 'py-2.5')
          .replace(/\bpy-4\b/g, 'py-2.5')
          .replace(/\bh-20\b/g, 'h-14')
          .replace(/\bh-16\b/g, 'h-12');
        if (updated !== file.content) {
          changed.add(file.path);
          return { ...file, content: updated };
        }
      }
      return file;
    });

    const overridePath = 'src/styles/mist-overrides.css';
    const existingOverride = nextFiles.find((f) => f.path === overridePath);
    const updatedCss = upsertOverrideCssBlock(
      existingOverride?.content ?? '',
      'mist-navbar-compact',
      ['padding-top: 0.625rem !important;', 'padding-bottom: 0.625rem !important;'],
    ).replace('[data-mist-id="mist-navbar-compact"]', 'header, nav');

    if (existingOverride) {
      nextFiles = nextFiles.map((f) =>
        f.path === overridePath ? { ...f, content: updatedCss } : f,
      );
    } else {
      nextFiles.push({
        id: createSafeId('file'),
        path: overridePath,
        language: 'css',
        content: updatedCss,
      });
    }
    changed.add(overridePath);
    summary = 'Reduced navbar vertical padding and tightened header height.';
  } else if (lower.includes('dark') && (lower.includes('theme') || lower.includes('mode') || lower.includes('background'))) {
    nextFiles = nextFiles.map((file) => {
      if (file.path === 'src/App.tsx' || file.path.includes('Navbar')) {
        const updated = file.content
          .replace(/bg-stone-50/g, 'bg-zinc-950')
          .replace(/bg-white/g, 'bg-zinc-900')
          .replace(/text-stone-900/g, 'text-zinc-100')
          .replace(/text-zinc-900/g, 'text-zinc-100');
        if (updated !== file.content) {
          changed.add(file.path);
          return { ...file, content: updated };
        }
      }
      return file;
    });
    summary = 'Shifted primary surface and typography palette to high-contrast dark slate.';
  } else {
    summary = `Applied targeted refinement for "${instruction.trim()}".`;
  }

  return {
    files: nextFiles,
    summary,
    changedFiles: Array.from(changed),
  };
}

export function buildExportManifest(
  project: MistProject,
  options?: { standaloneHtml?: string; slug?: string },
): Record<string, string> {
  const manifest: Record<string, string> = {};
  const cleanSlug = options?.slug ? sanitizeSlug(options.slug) : suggestShortSlug(project.name);

  const usesThreeJs = project.files.some((file) =>
    /from\s+['"]three(?:\/|['"])|import\s+['"]three['"]/.test(file.content),
  );

  manifest['package.json'] = JSON.stringify(
    {
      name: cleanSlug,
      private: true,
      version: '1.0.0',
      type: 'module',
      scripts: {
        dev: 'vite',
        build: 'tsc && vite build',
        preview: 'vite preview',
      },
      dependencies: {
        react: '^19.0.1',
        'react-dom': '^19.0.1',
        'lucide-react': '^0.546.0',
        ...(usesThreeJs ? { three: '^0.183.0' } : {}),
      },
      devDependencies: {
        '@tailwindcss/vite': '^4.1.0',
        '@vitejs/plugin-react': '^4.4.0',
        '@types/react': '^19.0.0',
        '@types/react-dom': '^19.0.0',
        ...(usesThreeJs ? { '@types/three': '^0.183.0' } : {}),
        tailwindcss: '^4.1.0',
        typescript: '^5.8.0',
        vite: '^6.2.0',
      },
    },
    null,
    2,
  );

  manifest['tsconfig.json'] = JSON.stringify(
    {
      compilerOptions: {
        target: 'ES2022',
        lib: ['ES2022', 'DOM', 'DOM.Iterable'],
        module: 'ESNext',
        moduleResolution: 'bundler',
        jsx: 'react-jsx',
        strict: true,
        noEmit: true,
        skipLibCheck: true,
      },
      include: ['src'],
    },
    null,
    2,
  );

  manifest['vite.config.ts'] = [
    "import { defineConfig } from 'vite';",
    "import react from '@vitejs/plugin-react';",
    "import tailwindcss from '@tailwindcss/vite';",
    '',
    'export default defineConfig({',
    '  plugins: [react(), tailwindcss()],',
    '});',
    '',
  ].join('\n');

  manifest['index.html'] = [
    '<!doctype html>',
    '<html lang="en">',
    '  <head>',
    '    <meta charset="UTF-8" />',
    '    <meta name="viewport" content="width=device-width, initial-scale=1.0" />',
    `    <title>${project.name.replace(/[<>]/g, '')}</title>`,
    '  </head>',
    '  <body>',
    '    <div id="root"></div>',
    '    <script type="module" src="/src/main.tsx"></script>',
    '  </body>',
    '</html>',
    '',
  ].join('\n');

  const hasMain = project.files.some((f) => f.path === 'src/main.tsx');
  if (!hasMain) {
    const hasCss = project.files.some((f) => f.path === 'src/index.css');
    const hasOverrides = project.files.some((f) => f.path === 'src/styles/mist-overrides.css');
    manifest['src/main.tsx'] = [
      "import { StrictMode } from 'react';",
      "import { createRoot } from 'react-dom/client';",
      hasCss ? "import './index.css';" : '',
      hasOverrides ? "import './styles/mist-overrides.css';" : '',
      "import App from './App';",
      '',
      "createRoot(document.getElementById('root')!).render(",
      '  <StrictMode>',
      '    <App />',
      '  </StrictMode>,',
      ');',
      '',
    ]
      .filter((line, idx, arr) => !(line === '' && arr[idx - 1] === ''))
      .join('\n');
  }

  for (const file of project.files) {
    manifest[file.path] = file.content;
  }

  if (options?.standaloneHtml) {
    manifest['dist/index.html'] = options.standaloneHtml;
  }

  manifest['render.yaml'] = [
    'services:',
    '  - type: web',
    `    name: ${cleanSlug}`,
    '    runtime: static',
    '    buildCommand: npm install && npm run build',
    '    staticPublishPath: ./dist',
    '    routes:',
    '      - type: rewrite',
    '        source: /*',
    '        destination: /index.html',
    '',
  ].join('\n');

  manifest['DEPLOY_FREE.md'] = [
    `# Publish "${project.name.replace(/[\r\n]/g, ' ')}" for Free (No Credit Card Required)`,
    '',
    'Your exported project runs 100% standalone on any free static host with zero traffic sent back to Mist.',
    '',
    'CAUTION: Choose ONLY static hosting plans with a free tier and no credit card billing required.',
    'Avoid paid server instances or hosts that require adding a credit card upfront.',
    '',
    '## Recommended Free Static Hosts (No Credit Card)',
    '1. Netlify Drop (Fastest - Drag & Drop): https://app.netlify.com/drop',
    '   - Unzip this file and drag the `dist` folder onto Netlify Drop to go live immediately.',
    '2. Render Static Sites (GitHub + render.yaml included): https://dashboard.render.com/select-repo?type=static',
    '   - Push this folder to a GitHub repo, pick "Static Site", set Build Command `npm install && npm run build`, Publish Directory `dist`.',
    '3. Vercel Hobby (Free Static): https://vercel.com/new',
    '4. Cloudflare Pages (Free Unlimited Static Bandwidth): https://dash.cloudflare.com/',
    '5. GitHub Pages (Free Public Repo Hosting): https://pages.github.com/',
    '',
  ].join('\n');

  return manifest;
}

