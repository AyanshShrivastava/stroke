import test from 'node:test';
import assert from 'node:assert/strict';
import {
  applyDeterministicRefinement,
  applyVisualPatchToFiles,
  buildExportManifest,
  duplicateProjectData,
  mergeProjectFiles,
  normalizeProjectFilePath,
  resolveAppEntryPath,
  sanitizeSlug,
} from './projectOps';
import type { MistProject } from '../types/mist';

const sampleProject: MistProject = {
  id: 'proj_sample_1',
  name: 'Kuro Coffee Tokyo',
  description: 'Minimalist Tokyo coffee roastery',
  prompt: 'Create a coffee shop landing page',
  files: [
    {
      id: 'f_app',
      path: 'src/App.tsx',
      language: 'tsx',
      content: `import Navbar from './components/Navbar';\nexport default function App() {\n  return (\n    <div className="min-h-screen bg-stone-50 text-stone-900">\n      <Navbar />\n      <main><h1>Hand-Roasted in Kiyosumi</h1></main>\n    </div>\n  );\n}`,
    },
    {
      id: 'f_nav',
      path: 'src/components/Navbar.tsx',
      language: 'tsx',
      content: `export default function Navbar() {\n  return <header className="py-6 px-8 border-b">Kuro Coffee</header>;\n}`,
    },
    {
      id: 'f_css',
      path: 'src/index.css',
      language: 'css',
      content: '@import "tailwindcss";\n',
    },
  ],
  chatHistory: [
    {
      id: 'm1',
      role: 'user',
      content: 'Create a coffee shop landing page',
      timestamp: '2026-11-14T00:00:00.000Z',
    },
  ],
  publishedSlug: 'kuro-coffee',
  isPublished: true,
  createdAt: '2026-11-14T00:00:00.000Z',
  updatedAt: '2026-11-14T00:00:00.000Z',
};

test('sanitizeSlug normalizes arbitrary titles into valid URL slugs', () => {
  assert.equal(sanitizeSlug('Kuro Coffee Tokyo!'), 'kuro-coffee-tokyo');
  assert.equal(sanitizeSlug('  My___Site 2026  '), 'my-site-2026');
  assert.ok(sanitizeSlug('!').startsWith('mist-site-'));
});

test('duplicateProjectData clones project with fresh IDs and unpublished status', () => {
  const copy = duplicateProjectData(sampleProject);
  assert.notEqual(copy.id, sampleProject.id);
  assert.equal(copy.name, 'Kuro Coffee Tokyo (Copy)');
  assert.equal(copy.isPublished, false);
  assert.equal(copy.publishedSlug, undefined);
  assert.equal(copy.files.length, sampleProject.files.length);
  assert.notEqual(copy.files[0].id, sampleProject.files[0].id);
});

test('applyVisualPatchToFiles updates JSX text and writes override CSS rule', () => {
  const updated = applyVisualPatchToFiles(sampleProject.files, {
    mistId: 'hero-title',
    originalText: 'Hand-Roasted in Kiyosumi',
    newText: 'Single-Origin Roastery in Tokyo',
    styles: {
      color: '#1e3a8a',
      fontSize: '48px',
    },
  });

  const appFile = updated.find((f) => f.path === 'src/App.tsx');
  assert.ok(appFile?.content.includes('Single-Origin Roastery in Tokyo'));

  const overrideCss = updated.find((f) => f.path === 'src/styles/mist-overrides.css');
  assert.ok(overrideCss);
  assert.ok(overrideCss.content.includes('[data-mist-id="hero-title"]'));
  assert.ok(overrideCss.content.includes('color: #1e3a8a !important;'));
});

test('applyDeterministicRefinement shrinks navbar height on "make the navbar smaller"', () => {
  const result = applyDeterministicRefinement(sampleProject.files, 'make the navbar smaller');
  const nav = result.files.find((f) => f.path === 'src/components/Navbar.tsx');
  assert.ok(nav?.content.includes('py-2.5'));
  assert.ok(result.changedFiles.includes('src/components/Navbar.tsx'));
});

test('mergeProjectFiles updates existing paths and adds new files cleanly', () => {
  const merged = mergeProjectFiles(sampleProject.files, [
    { path: './src/index.css', content: '@import "tailwindcss";\nbody { margin: 0; }' },
    { path: 'src/components/Footer.tsx', content: 'export default function Footer() { return <footer />; }' },
  ]);
  assert.equal(merged.length, 4);
  assert.ok(merged.find((f) => f.path === 'src/components/Footer.tsx'));
  assert.ok(merged.find((f) => f.path === 'src/index.css')?.content.includes('body { margin: 0; }'));
});

test('normalizeProjectFilePath & resolveAppEntryPath handle lowercase and alternative entry files', () => {
  assert.equal(normalizeProjectFilePath('./src/app.tsx'), 'src/App.tsx');
  assert.equal(normalizeProjectFilePath('/src/main.tsx'), 'src/main.tsx');
  assert.equal(
    resolveAppEntryPath([{ path: 'src/app.tsx', content: 'export default function App() { return <div />; }' }]),
    'src/App.tsx',
  );
  assert.equal(
    resolveAppEntryPath([{ path: 'App.tsx', content: 'export default function App() { return <div />; }' }]),
    'App.tsx',
  );
  assert.equal(
    resolveAppEntryPath([
      { path: 'src/components/Landing.tsx', content: 'export default function Landing() { return <main />; }' },
    ]),
    'src/components/Landing.tsx',
  );
});

test('buildExportManifest generates complete Vite + React + TS project files', () => {
  const manifest = buildExportManifest(sampleProject);
  assert.ok(manifest['package.json'].includes('"react"'));
  assert.ok(manifest['index.html'].includes('Kuro Coffee Tokyo'));
  assert.ok(manifest['vite.config.ts'].includes('@tailwindcss/vite'));
  assert.ok(manifest['src/main.tsx'].includes("import App from './App'"));
  assert.ok(manifest['src/App.tsx']);
  assert.ok(!manifest['package.json'].includes('"three"'));
});

test('buildExportManifest includes three and @types/three when Three.js is imported', () => {
  const threeProject: MistProject = {
    ...sampleProject,
    files: [
      {
        id: 'f_three',
        path: 'src/App.tsx',
        language: 'tsx',
        content: `import * as THREE from 'three';\nexport default function App() { void THREE.Scene; return <div />; }`,
      },
    ],
  };
  const manifest = buildExportManifest(threeProject);
  assert.ok(manifest['package.json'].includes('"three"'));
  assert.ok(manifest['package.json'].includes('"@types/three"'));
});

