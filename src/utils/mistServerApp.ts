import express, { type Express } from 'express';
import fs from 'node:fs';
import path from 'node:path';
import nodeCrypto from 'node:crypto';
import { createRequire } from 'node:module';
import * as esbuild from 'esbuild';
import { compile as compileTailwind } from 'tailwindcss';
import type {
  AiProviderConfig,
  AiProviderId,
  MistProject,
  ProjectFile,
  WebSearchConfig,
  WebSearchMode,
  WebSearchOutcome,
} from '../types/mist';
import {
  detectGatewayFromBaseUrl,
  normalizeProviderConfigToStudio,
  shouldEnableAppAi,
} from '../data/models';
import {
  needsWebSearch,
  normalizeWebSearchConfig,
  validateAndExtractCitations,
} from '../data/webSearch';
import { classifyModelError, type ModelHealthIncident } from './aiErrors';
import {
  maskApiKey,
  mergeProjectFiles,
  normalizeProjectFilePath,
  resolveAppEntryPath,
} from './projectOps';
import {
  BODY_LIMITS,
  BUILDER_CSP,
  createBodySizeLimitMiddleware,
  createClerkAuthMiddleware,
  createEdgeOriginSecretMiddleware,
  createFirebaseAuthMiddleware,
  createOptionalAuthMiddleware,
  createPreviewAiSession,
  createRateLimiter,
  enforceHostOnlyCookies,
  enforceSameOriginOnMutations,
  getEffectiveHost,
  getFirebaseAppletConfig,
  handleBodyParserErrors,
  isPublishingHostname,
  resolvePreviewAiSession,
  revokeAllUserPreviewSessions,
  revokePreviewAiSession,
  sanitizeErrorMessage,
  sealUserVaultPayload,
  SecurityValidationError,
  sendPublishedSiteHtml,
  sendSecurityErrorResponse,
  unsealUserVaultPayload,
  validateAiProviderConfig,
  validateExternalUrlSyntax,
  validateProjectFilesPayload,
  validateProjectPayload,
  validateVaultPayload,
  validateWebSearchConfig,
  verifyClerkAuthHeader,
  verifyFirebaseAuthHeader,
  type AuthenticatedRequest,
  type SharedRateLimitAdapter,
  type VerifiedClerkUser,
  type VerifiedFirebaseUser,
} from './serverSecurity';
import { fetchGatewayModelsCatalog } from './modelCatalogServer';
import {
  callByokCompletionRaw,
  getHttpStatusFromError,
  probeProviderCapabilities,
  resolveByokRequestParams,
  streamByokCompletion,
} from './byokClient';
import {
  createFirestoreDeploymentStore,
  formatDeploymentUrl,
  type DeploymentStore,
} from './deploymentStore';
import {
  validateRenderApiKey,
  validateGitHubRepoUrl,
  validateRenderServiceName,
  verifyRenderApiKey,
  createRenderStaticSite,
  getRenderService,
  getRenderLatestDeploy,
  triggerRenderDeploy,
  listRenderStaticSites,
} from './renderClient';
import type { RenderCredentialConfig, VaultPlainPayload } from './serverSecurity';
import {
  FirestoreAdminStore,
  InMemoryAdminStore,
  type AdminDatabaseOperations,
} from '../server/firestoreAdmin';
import {
  CloudflareR2ArtifactStore,
  InMemoryR2ArtifactStore,
  type R2StorageOperations,
} from './r2ArtifactStore';

import {
  defaultWebSearchService,
  formatRetrievedSourcesForPrompt,
  formatSearchFailureForPrompt,
  MAX_SEARCH_REQUESTS_PER_INTERACTION,
  WebSearchError,
  type WebSearchService,
} from './webSearchService';
import {
  defaultNotificationService,
  PushNotificationService,
  type NotificationPayload,
  type WebPushSubscription,
} from './notificationService';

const require = createRequire(import.meta.url);

// --- 1. Vendor Runtime Cache for Preview & Deployed Sites ---
let cachedVendorBundle: string | null = null;
let reactExportNames: string[] = [];
let lucideExportNames: string[] = [];

export async function ensureVendorRuntime(): Promise<string> {
  if (cachedVendorBundle) return cachedVendorBundle;

  const reactMod = require('react');
  const lucideMod = require('lucide-react');

  reactExportNames = Object.keys(reactMod).filter(
    (k) => /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k) && k !== 'default' && k !== '__esModule',
  );
  lucideExportNames = Object.keys(lucideMod).filter(
    (k) => /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k) && k !== 'default' && k !== '__esModule',
  );

  const entrySource = `
    import * as React from 'react';
    import * as ReactDOMClient from 'react-dom/client';
    import * as jsxRuntime from 'react/jsx-runtime';
    import * as LucideReact from 'lucide-react';
    window.__MIST_VENDOR__ = { React, ReactDOMClient, jsxRuntime, LucideReact };
  `;

  const result = await esbuild.build({
    stdin: {
      contents: entrySource,
      resolveDir: process.cwd(),
      loader: 'js',
    },
    bundle: true,
    write: false,
    format: 'iife',
    minify: true,
    define: {
      'process.env.NODE_ENV': '"production"',
    },
  });

  cachedVendorBundle = result.outputFiles[0].text;
  return cachedVendorBundle;
}

// --- 2. Tailwind v4 Compiler Cache ---
let cachedTailwindCompiler: Awaited<ReturnType<typeof compileTailwind>> | null = null;

async function getTailwindCompiler() {
  if (cachedTailwindCompiler) return cachedTailwindCompiler;
  const twDir = path.resolve(process.cwd(), 'node_modules/tailwindcss');
  const baseCss = fs.readFileSync(path.join(twDir, 'index.css'), 'utf8');
  cachedTailwindCompiler = await compileTailwind(baseCss, {
    loadStylesheet: async (id, base) => {
      const candidate = path.resolve(twDir, id);
      if (fs.existsSync(candidate)) {
        return { path: candidate, base, content: fs.readFileSync(candidate, 'utf8') };
      }
      return { path: id, base, content: '' };
    },
  });
  return cachedTailwindCompiler;
}

function extractTailwindCandidates(files: ProjectFile[]): string[] {
  const tokens = new Set<string>();
  const regex = /[A-Za-z0-9_:\-/\[\]\.#%]+/g;
  for (const file of files) {
    if (file.language === 'tsx' || file.language === 'ts' || file.language === 'html') {
      const matches = file.content.match(regex);
      if (matches) {
        for (const m of matches) {
          if (m.length > 1 && m.length < 80) {
            tokens.add(m);
          }
        }
      }
    }
  }
  return Array.from(tokens);
}

function escapeInlineScript(js: string): string {
  return js.replace(/<\/script/gi, '<\\/script');
}

// --- 3. Multi-File React + TSX + Three.js Bundler ---
const INSPECTOR_BRIDGE_SCRIPT = `
(function() {
  var inspectorActive = false;
  var selectedMistId = null;
  var hoverOverlay = null;
  var selectOverlay = null;
  var tagBadge = null;
  var ALLOWED_STYLES = {
    color: true,
    backgroundColor: true,
    fontSize: true,
    fontWeight: true,
    paddingTop: true,
    paddingBottom: true,
    paddingLeft: true,
    paddingRight: true,
    borderRadius: true,
    textAlign: true
  };

  function isSafeMistId(id) {
    return typeof id === 'string' && /^el-\\d+$/.test(id);
  }

  function ensureOverlays() {
    if (!hoverOverlay) {
      hoverOverlay = document.createElement('div');
      hoverOverlay.setAttribute('data-mist-ui', 'true');
      hoverOverlay.style.cssText = 'position:fixed;pointer-events:none;z-index:2147483646;border:1.5px dashed #2563eb;background:rgba(37,99,235,0.06);border-radius:3px;display:none;transition:all 60ms ease;';
      tagBadge = document.createElement('span');
      tagBadge.style.cssText = 'position:absolute;top:-20px;left:-1px;background:#2563eb;color:#fff;font:600 10px/16px ui-monospace,monospace;padding:0 5px;border-radius:2px;white-space:nowrap;';
      hoverOverlay.appendChild(tagBadge);
      document.body.appendChild(hoverOverlay);
    }
    if (!selectOverlay) {
      selectOverlay = document.createElement('div');
      selectOverlay.setAttribute('data-mist-ui', 'true');
      selectOverlay.style.cssText = 'position:fixed;pointer-events:none;z-index:2147483645;border:2px solid #2563eb;background:rgba(37,99,235,0.04);border-radius:3px;display:none;';
      document.body.appendChild(selectOverlay);
    }
  }

  function assignIds() {
    var root = document.getElementById('root');
    if (!root) return;
    var els = root.querySelectorAll('*');
    var idx = 0;
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (!el.getAttribute('data-mist-id')) {
        el.setAttribute('data-mist-id', 'el-' + (idx++));
      } else {
        idx++;
      }
    }
  }

  function cssColorToHex(cssColor) {
    if (!cssColor || cssColor === 'transparent' || cssColor === 'rgba(0, 0, 0, 0)') return '';
    if (/^#[0-9a-fA-F]{6}$/.test(cssColor)) return cssColor.toLowerCase();
    try {
      var canvas = document.createElement('canvas');
      canvas.width = 1;
      canvas.height = 1;
      var ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.clearRect(0, 0, 1, 1);
        ctx.fillStyle = cssColor;
        ctx.fillRect(0, 0, 1, 1);
        var d = ctx.getImageData(0, 0, 1, 1).data;
        if (d[3] === 0) return '';
        return '#' + [d[0], d[1], d[2]].map(function(x) {
          return x.toString(16).padStart(2, '0');
        }).join('');
      }
    } catch (err) {}
    return '';
  }

  function positionBox(box, el) {
    if (!box || !el) return;
    var r = el.getBoundingClientRect();
    box.style.top = r.top + 'px';
    box.style.left = r.left + 'px';
    box.style.width = r.width + 'px';
    box.style.height = r.height + 'px';
    box.style.display = 'block';
  }

  function sendSelection(el) {
    var cs = window.getComputedStyle(el);
    var canEditText = el.children.length === 0;
    var mistId = el.getAttribute('data-mist-id') || '';
    selectedMistId = mistId;
    ensureOverlays();
    positionBox(selectOverlay, el);
    window.parent.postMessage({
      type: 'MIST_SELECT_ELEMENT',
      payload: {
        mistId: mistId,
        tagName: el.tagName.toLowerCase(),
        textContent: canEditText ? (el.textContent || '').trim() : '',
        className: typeof el.className === 'string' ? el.className : '',
        canEditText: canEditText,
        styles: {
          color: cssColorToHex(cs.color) || '#09090b',
          backgroundColor: cssColorToHex(cs.backgroundColor) || '',
          fontSize: cs.fontSize,
          fontWeight: cs.fontWeight,
          paddingTop: cs.paddingTop,
          paddingBottom: cs.paddingBottom,
          paddingLeft: cs.paddingLeft,
          paddingRight: cs.paddingRight,
          borderRadius: cs.borderRadius,
          textAlign: cs.textAlign
        }
      }
    }, '*');
  }

  document.addEventListener('mouseover', function(e) {
    if (!inspectorActive) return;
    var target = e.target;
    if (!target || !(target instanceof Element)) return;
    if (target.closest('[data-mist-ui="true"]') || !document.getElementById('root')?.contains(target)) return;
    ensureOverlays();
    tagBadge.textContent = target.tagName.toLowerCase();
    positionBox(hoverOverlay, target);
  }, true);

  document.addEventListener('click', function(e) {
    if (!inspectorActive) return;
    var target = e.target;
    if (!target || !(target instanceof Element)) return;
    if (target.closest('[data-mist-ui="true"]') || !document.getElementById('root')?.contains(target)) return;
    e.preventDefault();
    e.stopPropagation();
    assignIds();
    sendSelection(target);
  }, true);

  window.addEventListener('scroll', function() {
    if (isSafeMistId(selectedMistId) && selectOverlay) {
      var el = document.querySelector('[data-mist-id="' + selectedMistId + '"]');
      if (el) positionBox(selectOverlay, el);
    }
  }, true);

  window.addEventListener('message', function(e) {
    if (e.source !== window.parent) return;
    if (!e.data || typeof e.data !== 'object') return;
    if (e.data.type === 'MIST_TOGGLE_INSPECTOR') {
      inspectorActive = Boolean(e.data.enabled);
      document.body.style.cursor = inspectorActive ? 'crosshair' : '';
      if (!inspectorActive) {
        if (hoverOverlay) hoverOverlay.style.display = 'none';
        if (selectOverlay) selectOverlay.style.display = 'none';
      } else {
        assignIds();
      }
    } else if (e.data.type === 'MIST_LIVE_PATCH') {
      var patch = e.data.payload || {};
      if (!isSafeMistId(patch.mistId)) return;
      var target = document.querySelector('[data-mist-id="' + patch.mistId + '"]');
      if (!target) return;
      if (patch.deleted) {
        target.style.display = 'none';
        if (selectOverlay) selectOverlay.style.display = 'none';
        return;
      }
      if (typeof patch.newText === 'string' && target.children.length === 0) {
        target.textContent = patch.newText;
      }
      if (patch.styles && typeof patch.styles === 'object') {
        Object.keys(patch.styles).forEach(function(k) {
          if (ALLOWED_STYLES[k] && typeof patch.styles[k] === 'string' && patch.styles[k] !== '') {
            target.style[k] = patch.styles[k];
          }
        });
      }
      if (selectOverlay && inspectorActive) positionBox(selectOverlay, target);
    }
  });

  window.addEventListener('DOMContentLoaded', function() {
    assignIds();
    var root = document.getElementById('root');
    if (root && typeof MutationObserver !== 'undefined') {
      new MutationObserver(assignIds).observe(root, { childList: true, subtree: true });
    }
  });
})();
`;

function collectImportedLucideSymbols(files: ProjectFile[]): string[] {
  const extra = new Set<string>();
  const importRegex = /import\s*\{([^}]+)\}\s*from\s*['"]lucide-react['"]/g;
  for (const f of files) {
    let match: RegExpExecArray | null;
    while ((match = importRegex.exec(f.content)) !== null) {
      const parts = match[1].split(',');
      for (const part of parts) {
        const cleaned = part.trim().split(/\s+as\s+/)[0].trim();
        if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(cleaned)) {
          extra.add(cleaned);
        }
      }
    }
  }
  return Array.from(extra);
}

function resolveThreeModulePath(specifier: string): string | null {
  const threeDir = path.resolve(process.cwd(), 'node_modules/three');
  if (specifier === 'three') {
    return path.join(threeDir, 'build/three.module.js');
  }
  if (specifier === 'three/addons') {
    return path.join(threeDir, 'examples/jsm/Addons.js');
  }
  if (specifier.startsWith('three/addons/')) {
    const rel = specifier.slice('three/addons/'.length);
    const candidate = path.join(threeDir, 'examples/jsm', rel);
    if (fs.existsSync(candidate)) return candidate;
    if (fs.existsSync(`${candidate}.js`)) return `${candidate}.js`;
  }
  if (specifier.startsWith('three/examples/jsm/')) {
    const rel = specifier.slice('three/examples/jsm/'.length);
    const candidate = path.join(threeDir, 'examples/jsm', rel);
    if (fs.existsSync(candidate)) return candidate;
    if (fs.existsSync(`${candidate}.js`)) return `${candidate}.js`;
  }
  if (specifier.startsWith('three/')) {
    const rel = specifier.slice('three/'.length);
    const candidate = path.join(threeDir, rel);
    if (fs.existsSync(candidate)) return candidate;
    if (fs.existsSync(`${candidate}.js`)) return `${candidate}.js`;
  }
  return null;
}

export async function bundleProjectToHtml(params: {
  files: ProjectFile[];
  title: string;
  includeInspector?: boolean;
  enableAppAi?: boolean;
  standaloneExport?: boolean;
}): Promise<{ html: string; bundleError?: string }> {
  const vendorBundle = await ensureVendorRuntime();

  const fileMap = new Map<string, ProjectFile>();
  const lowerFileMap = new Map<string, string>();
  const missingImports = new Set<string>();
  const normalizedFiles: ProjectFile[] = params.files.map((f) => {
    const cleanPath = normalizeProjectFilePath(f.path);
    return { ...f, path: cleanPath };
  });

  for (const f of normalizedFiles) {
    fileMap.set(f.path, f);
    lowerFileMap.set(f.path.toLowerCase(), f.path);
  }

  const importedLucideSymbols = collectImportedLucideSymbols(normalizedFiles);
  const allLucideExports = Array.from(new Set([...lucideExportNames, ...importedLucideSymbols]));

  const appEntry = resolveAppEntryPath(normalizedFiles);
  const entryPath = fileMap.has('src/main.tsx') ? 'src/main.tsx' : '__mist_entry.tsx';

  const syntheticEntry = appEntry
    ? `
    import React from 'react';
    import { createRoot } from 'react-dom/client';
    import * as AppModule from './${appEntry}';

    const ResolvedApp =
      AppModule.default ||
      AppModule.App ||
      Object.values(AppModule).find((val) => typeof val === 'function') ||
      (() => React.createElement('div', { className: 'p-8 text-center font-sans text-zinc-700' }, 'Export a React component from ${appEntry} to render this website.'));

    class MistErrorBoundary extends React.Component {
      constructor(props) {
        super(props);
        this.state = { error: null };
      }
      static getDerivedStateFromError(error) {
        return { error };
      }
      render() {
        if (this.state.error) {
          return React.createElement(
            'div',
            { className: 'p-6 m-4 rounded-xl border border-red-200 bg-red-50 text-red-900 font-sans text-sm' },
            React.createElement('strong', null, 'Preview Render Error'),
            React.createElement('pre', { className: 'mt-2 text-xs font-mono whitespace-pre-wrap' }, String(this.state.error?.message || this.state.error))
          );
        }
        return this.props.children;
      }
    }

    const rootEl = document.getElementById('root');
    if (rootEl) {
      createRoot(rootEl).render(
        React.createElement(MistErrorBoundary, null, React.createElement(ResolvedApp))
      );
    }
  `
    : `
    import React from 'react';
    import { createRoot } from 'react-dom/client';
    const rootEl = document.getElementById('root');
    if (rootEl) {
      createRoot(rootEl).render(
        React.createElement('div', { className: 'p-12 text-center font-sans text-zinc-600' }, 'Add src/App.tsx to render your website.')
      );
    }
  `;

  const virtualPlugin: esbuild.Plugin = {
    name: 'mist-virtual-fs',
    setup(build) {
      build.onResolve({ filter: /^react$/ }, () => ({ path: 'react', namespace: 'mist-vendor' }));
      build.onResolve({ filter: /^react-dom\/client$/ }, () => ({
        path: 'react-dom/client',
        namespace: 'mist-vendor',
      }));
      build.onResolve({ filter: /^react\/jsx-runtime$/ }, () => ({
        path: 'react/jsx-runtime',
        namespace: 'mist-vendor',
      }));
      build.onResolve({ filter: /^react\/jsx-dev-runtime$/ }, () => ({
        path: 'react/jsx-runtime',
        namespace: 'mist-vendor',
      }));
      build.onResolve({ filter: /^lucide-react$/ }, () => ({
        path: 'lucide-react',
        namespace: 'mist-vendor',
      }));

      build.onResolve({ filter: /^three(\/.*)?$/ }, (args) => {
        const resolved = resolveThreeModulePath(args.path);
        if (resolved) {
          return { path: resolved, namespace: 'file' };
        }
        return undefined;
      });

      build.onResolve({ filter: /.*/ }, (args) => {
        if (args.resolveDir && args.importer && !fileMap.has(args.importer) && args.importer !== entryPath) {
          return undefined;
        }
        if (args.path === entryPath) {
          return { path: entryPath, namespace: 'mist-fs' };
        }
        if (args.path.endsWith('.css')) {
          return { path: args.path, namespace: 'mist-css-noop' };
        }
        const importerDir =
          args.importer && args.importer !== entryPath ? path.posix.dirname(args.importer) : '';
        const baseResolved = args.path.startsWith('.')
          ? path.posix.normalize(path.posix.join(importerDir, args.path))
          : args.path.replace(/^(@\/|\/)/, '');

        const rawCandidates = [
          baseResolved,
          `${baseResolved}.tsx`,
          `${baseResolved}.ts`,
          `${baseResolved}.jsx`,
          `${baseResolved}.js`,
          `${baseResolved}/index.tsx`,
          `${baseResolved}/index.ts`,
        ];
        if (!baseResolved.startsWith('src/')) {
          rawCandidates.push(
            `src/${baseResolved}`,
            `src/${baseResolved}.tsx`,
            `src/${baseResolved}.ts`,
            `src/${baseResolved}.jsx`,
            `src/${baseResolved}.js`,
            `src/${baseResolved}/index.tsx`,
          );
        }
        for (const c of rawCandidates) {
          if (fileMap.has(c)) {
            return { path: c, namespace: 'mist-fs' };
          }
          const matched = lowerFileMap.get(c.toLowerCase());
          if (matched) {
            return { path: matched, namespace: 'mist-fs' };
          }
        }
        missingImports.add(args.path);
        return { path: args.path, namespace: 'mist-missing' };
      });

      build.onLoad({ filter: /.*/, namespace: 'mist-vendor' }, (args) => {
        if (args.path === 'react') {
          const named = reactExportNames
            .map((k) => `export const ${k} = window.__MIST_VENDOR__.React["${k}"];`)
            .join('\n');
          return {
            contents: `const React = window.__MIST_VENDOR__.React;\nexport default React;\n${named}`,
            loader: 'js',
          };
        }
        if (args.path === 'react-dom/client') {
          return {
            contents: `const RDC = window.__MIST_VENDOR__.ReactDOMClient;\nexport default RDC;\nexport const createRoot = RDC.createRoot;\nexport const hydrateRoot = RDC.hydrateRoot;`,
            loader: 'js',
          };
        }
        if (args.path === 'react/jsx-runtime') {
          return {
            contents: `const J = window.__MIST_VENDOR__.jsxRuntime;\nexport const jsx = J.jsx;\nexport const jsxs = J.jsxs;\nexport const Fragment = J.Fragment;`,
            loader: 'js',
          };
        }
        if (args.path === 'lucide-react') {
          const lucideHeader = `
            const React = window.__MIST_VENDOR__.React;
            const LR = window.__MIST_VENDOR__.LucideReact;
            function FallbackIcon(props) {
              return React.createElement('svg', {
                viewBox: '0 0 24 24',
                width: props?.size || 16,
                height: props?.size || 16,
                fill: 'none',
                stroke: 'currentColor',
                strokeWidth: 2,
                strokeLinecap: 'round',
                strokeLinejoin: 'round',
                className: props?.className || '',
                'aria-hidden': 'true'
              }, React.createElement('circle', { cx: 12, cy: 12, r: 9 }));
            }
          `;
          const icons = allLucideExports
            .map((k) => `export const ${k} = LR["${k}"] || FallbackIcon;`)
            .join('\n');
          return { contents: `${lucideHeader}\n${icons}`, loader: 'js' };
        }
        return { contents: '', loader: 'js' };
      });

      build.onLoad({ filter: /.*/, namespace: 'mist-css-noop' }, () => ({
        contents: '',
        loader: 'js',
      }));

      build.onLoad({ filter: /.*/, namespace: 'mist-missing' }, (args) => ({
        contents: `export default function MissingModule() { return null; } /* Missing: ${args.path} */`,
        loader: 'js',
      }));

      build.onLoad({ filter: /.*/, namespace: 'mist-fs' }, (args) => {
        if (args.path === '__mist_entry.tsx') {
          return { contents: syntheticEntry, loader: 'tsx', resolveDir: process.cwd() };
        }
        const file = fileMap.get(args.path);
        if (!file) return { contents: '', loader: 'tsx', resolveDir: process.cwd() };
        const loader = file.path.endsWith('.ts')
          ? 'ts'
          : file.path.endsWith('.json')
            ? 'json'
            : 'tsx';
        return { contents: file.content, loader, resolveDir: process.cwd() };
      });
    },
  };

  let jsBundle = '';
  let bundleError: string | undefined;

  const formatBuildErrorScript = (msg: string) => `
      const root = document.getElementById('root');
      if (root) {
        const box = document.createElement('div');
        box.setAttribute('style', 'padding:32px;font-family:ui-monospace,monospace;color:#991b1b;background:#fef2f2;border:1px solid #fecaca;margin:24px;border-radius:8px;');
        const title = document.createElement('strong');
        title.textContent = 'Build Error';
        const pre = document.createElement('pre');
        pre.setAttribute('style', 'margin-top:12px;white-space:pre-wrap;font-size:12px;');
        pre.textContent = ${JSON.stringify(msg)};
        box.appendChild(title);
        box.appendChild(pre);
        root.replaceChildren(box);
      }
    `;

  try {
    const buildResult = await esbuild.build({
      entryPoints: [entryPath],
      bundle: true,
      write: false,
      minify: true,
      format: 'iife',
      jsx: 'automatic',
      plugins: [virtualPlugin],
      logLevel: 'silent',
    });
    if (missingImports.size > 0) {
      bundleError = `Missing or unsupported external import(s): ${Array.from(missingImports).join(', ')}`;
      jsBundle = formatBuildErrorScript(bundleError);
    } else {
      jsBundle = buildResult.outputFiles[0]?.text || '';
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    bundleError = msg;
    jsBundle = formatBuildErrorScript(msg);
  }

  let compiledTwCss = '';
  try {
    const twCompiler = await getTailwindCompiler();
    const candidates = extractTailwindCandidates(params.files);
    compiledTwCss = twCompiler.build(candidates);
  } catch {
    compiledTwCss = '';
  }

  const customCss = params.files
    .filter((f) => f.language === 'css')
    .map((f) => f.content.replace(/@import\s+["']tailwindcss["'];?/g, ''))
    .join('\n')
    .replace(/<\/style/gi, '<\\/style');

  const safeTitle = params.title.replace(/[<>]/g, '');
  const isStandaloneExport = Boolean(params.standaloneExport);
  const initialAppAiEnabled = isStandaloneExport ? false : Boolean(params.enableAppAi);
  const inlineVendorScript = Boolean(params.includeInspector) || isStandaloneExport;
  const includeInspector = isStandaloneExport ? false : Boolean(params.includeInspector);

  // Runtime sandbox compatibility (isolated storage shim inside opaque srcDoc without allow-same-origin,
  // plus authenticated parent postMessage relay for /api/app-ai so no keys/tokens leak into the iframe).
  const MIST_APP_AI_RUNTIME_SCRIPT = `
(function() {
  var appAiEnabled = ${initialAppAiEnabled ? 'true' : 'false'};
  var isOpaqueSandbox = window.location.origin === 'null' || window.location.protocol === 'about:';
  var origFetch = window.fetch ? window.fetch.bind(window) : null;
  var pendingAiRequests = {};
  var reqCounter = 0;

  // Provide isolated in-memory Storage inside opaque sandbox so generated apps using localStorage work safely
  function makeMemoryStorage() {
    var data = Object.create(null);
    return {
      getItem: function(k) { return Object.prototype.hasOwnProperty.call(data, String(k)) ? data[String(k)] : null; },
      setItem: function(k, v) { data[String(k)] = String(v); },
      removeItem: function(k) { delete data[String(k)]; },
      clear: function() { data = Object.create(null); },
      key: function(i) { var keys = Object.keys(data); return keys[i] || null; },
      get length() { return Object.keys(data).length; }
    };
  }
  try { void window.localStorage.length; } catch (e) {
    try { Object.defineProperty(window, 'localStorage', { value: makeMemoryStorage(), configurable: true }); } catch (_) {}
  }
  try { void window.sessionStorage.length; } catch (e) {
    try { Object.defineProperty(window, 'sessionStorage', { value: makeMemoryStorage(), configurable: true }); } catch (_) {}
  }

  window.addEventListener('message', function(e) {
    if (e.source !== window.parent) return;
    if (!e.data || typeof e.data !== 'object') return;
    if (e.data.type === 'MIST_SET_APP_AI_STATE') {
      var payload = e.data.payload || {};
      if (typeof payload.appAiEnabled === 'boolean') {
        appAiEnabled = payload.appAiEnabled;
      }
    } else if (e.data.type === 'MIST_APP_AI_RESPONSE') {
      var reqId = e.data.requestId;
      var entry = pendingAiRequests[reqId];
      if (!entry) return;
      delete pendingAiRequests[reqId];
      if (e.data.ok) {
        entry.resolve(e.data);
      } else {
        entry.reject(new Error(e.data.error || 'AI request failed'));
      }
    }
  });

  function relayAppAiViaParent(bodyObj) {
    if (!appAiEnabled) {
      return Promise.reject(new Error('Live App AI is disabled for this project unless requested or enabled in Mist.'));
    }
    return new Promise(function(resolve, reject) {
      var requestId = 'mist_ai_' + (++reqCounter) + '_' + Date.now();
      var timer = setTimeout(function() {
        if (pendingAiRequests[requestId]) {
          delete pendingAiRequests[requestId];
          reject(new Error('App AI request timed out.'));
        }
      }, 60000);
      pendingAiRequests[requestId] = {
        resolve: function(res) { clearTimeout(timer); resolve(res); },
        reject: function(err) { clearTimeout(timer); reject(err); }
      };
      window.parent.postMessage({
        type: 'MIST_APP_AI_REQUEST',
        requestId: requestId,
        payload: bodyObj || {}
      }, '*');
    });
  }

  if (origFetch) {
    window.fetch = function(input, init) {
      try {
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        if (isOpaqueSandbox && url.indexOf('/api/app-ai') !== -1 && window.parent !== window) {
          var bodyObj = {};
          if (init && typeof init.body === 'string') {
            try { bodyObj = JSON.parse(init.body); } catch (_) {}
          }
          return relayAppAiViaParent(bodyObj).then(function(res) {
            return new Response(JSON.stringify({ text: res.text, provider: res.provider, model: res.model }), {
              status: 200,
              headers: { 'Content-Type': 'application/json' }
            });
          }, function(err) {
            return new Response(JSON.stringify({ error: err.message || 'App AI failed' }), {
              status: 400,
              headers: { 'Content-Type': 'application/json' }
            });
          });
        }
      } catch (err) {}
      return origFetch(input, init);
    };
  }

  document.addEventListener('click', function(e) {
    var el = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!el) return;
    var href = el.getAttribute('href') || '';
    if (el.hasAttribute('download') || el.getAttribute('target') === '_blank') return;
    if (href.startsWith('#')) {
      e.preventDefault();
      var id = href.slice(1);
      if (id) {
        var target = document.getElementById(id);
        if (target && target.scrollIntoView) target.scrollIntoView({ behavior: 'smooth' });
      }
      return;
    }
    if (href.startsWith('/') && !href.startsWith('/p/')) {
      e.preventDefault();
    }
  }, false);

  window.mistAI = {
    isEnabled: function() { return appAiEnabled; },
    complete: async function(prompt, options) {
      if (!appAiEnabled) {
        throw new Error('Live App AI is disabled for this project unless requested or enabled in Mist.');
      }
      var opts = options || {};
      var payload = {
        prompt: prompt,
        messages: opts.messages,
        systemInstruction: opts.systemInstruction,
        jsonMode: Boolean(opts.jsonMode)
      };
      if (isOpaqueSandbox && window.parent !== window) {
        var relayed = await relayAppAiViaParent(payload);
        return relayed.text;
      }
      var res = await window.fetch('/api/app-ai', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      var data = await res.json();
      if (!res.ok) {
        throw new Error((data && (data.error || (data.incident && data.incident.message))) || 'AI request failed');
      }
      return data.text;
    },
    chat: async function(messages, systemInstruction) {
      return window.mistAI.complete('', { messages: messages, systemInstruction: systemInstruction });
    }
  };
})();
`;

  const vendorScriptTag = inlineVendorScript
    ? `<script>${escapeInlineScript(vendorBundle)}</script>`
    : `<script src="/vendor/preview-runtime.js"></script>`;

  const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${safeTitle}</title>
    <style>${compiledTwCss}</style>
    <style>${customCss}</style>
    ${vendorScriptTag}
    ${isStandaloneExport ? '' : `<script>${escapeInlineScript(MIST_APP_AI_RUNTIME_SCRIPT)}</script>`}
  </head>
  <body>
    <div id="root"></div>
    <script>${escapeInlineScript(jsBundle)}</script>
    ${includeInspector ? `<script>${escapeInlineScript(INSPECTOR_BRIDGE_SCRIPT)}</script>` : ''}
  </body>
</html>`;

  return { html, bundleError };
}

export interface ProjectVerificationResult {
  verified: boolean;
  buildOk: boolean;
  filesFingerprint: string;
  bundleError?: string;
  warnings: string[];
  verifiedAt: string;
}

export function computeProjectFilesFingerprint(files: ProjectFile[]): string {
  const normalized = [...files]
    .map((f) => ({ path: normalizeProjectFilePath(f.path), content: String(f.content || '') }))
    .sort((a, b) => a.path.localeCompare(b.path));
  return nodeCrypto.createHash('sha256').update(JSON.stringify(normalized)).digest('hex');
}

export function isVerificationValidForFiles(
  verification: ProjectVerificationResult | undefined | null,
  files: ProjectFile[],
): boolean {
  if (!verification || !verification.verified || !verification.buildOk) {
    return false;
  }
  return verification.filesFingerprint === computeProjectFilesFingerprint(files);
}

export async function verifyFinalProjectState(params: {
  files: ProjectFile[];
  title: string;
  priorVerification?: ProjectVerificationResult | null;
}): Promise<ProjectVerificationResult> {
  const fingerprint = computeProjectFilesFingerprint(params.files);
  if (
    params.priorVerification &&
    params.priorVerification.filesFingerprint === fingerprint &&
    params.priorVerification.verified
  ) {
    return params.priorVerification;
  }

  const warnings: string[] = [];
  if (!params.files.some((f) => normalizeProjectFilePath(f.path).toLowerCase() === 'src/index.css')) {
    warnings.push('src/index.css is missing.');
  }

  try {
    const { bundleError } = await bundleProjectToHtml({
      files: params.files,
      title: params.title,
      includeInspector: false,
      enableAppAi: false,
      standaloneExport: true,
    });
    const buildOk = !bundleError;
    return {
      verified: buildOk,
      buildOk,
      filesFingerprint: fingerprint,
      ...(bundleError ? { bundleError } : {}),
      warnings,
      verifiedAt: new Date().toISOString(),
    };
  } catch (err) {
    return {
      verified: false,
      buildOk: false,
      filesFingerprint: fingerprint,
      bundleError: sanitizeErrorMessage(err) || 'Verification bundle failed.',
      warnings,
      verifiedAt: new Date().toISOString(),
    };
  }
}

// --- 4. Pure BYOK AI Generation & Prompt Templates ---
const SYSTEM_GENERATOR_PROMPT = `You are Mist, a senior product designer, interactive game developer, and React + TypeScript + Tailwind CSS + Three.js engineer.
Generate clean, cohesive, responsive, fully playable/interactive web apps with strong contrast, crisp typography, mobile support, and zero broken links.

LIGHTWEIGHT & HIGH-RELIABILITY ARCHITECTURE RULES:
- Structure each project cleanly into 2 to 5 cohesive files max (e.g., src/App.tsx + 1-3 well-defined files in src/components/* + src/index.css). Keep state & types coherent across files so zero imports or props are broken.
- Verify that EVERY local import (e.g. import Header from './components/Header') matches an actual file you return AND that the exported default/named symbol exists identically.
- Write complete, rich, production-grade TypeScript code — NEVER use "// TODO", "...rest of code", empty click handlers, or placeholder cards.
- Build genuine mobile-first + desktop responsive layouts (sm:, md:, lg: grids/flex, touch-friendly >=40px tap targets, no horizontal overflow on 390px viewports).
- Use React 19, TypeScript (.tsx), and Tailwind CSS utility classes.
- Allowed imports ONLY: 'react', 'react-dom/client', 'lucide-react', 'three', 'three/addons/*' (e.g., OrbitControls, RoomEnvironment), and local relative imports like './components/Navbar'.
- NEVER import '@react-three/fiber', '@react-three/drei', 'framer-motion', 'axios', or any other external npm packages — they are NOT installed in Mist's runtime and WILL fail the build. For 3D scenes/games, ALWAYS use pure 'three' ('import * as THREE from "three"') inside useEffect.
- NEVER use Sparkles, Star, or Wand icons from lucide-react; prefer crisp functional icons (Send, Play, RotateCcw, Cpu, ArrowRight, Terminal, Layers, Check, Pause, Trophy, Volume2).
- NEVER return raw HTML documents ('<!doctype html>', '<script>', or raw HTML strings in JSX) — write pure TypeScript React components with working event handlers.
- NEVER use <a href="/..."> links on interactive buttons (such as "Play Game", "Start", "Restart") — ALWAYS use <button type="button" onClick={...}> so clicks never navigate away from the app.
- Ensure src/App.tsx is the default-exported root component and src/index.css starts with @import "tailwindcss";.
- Never use broken external URLs like unsplash.com or external .hdr/.gltf files; use crisp inline SVG graphics, Canvas2D procedural art, or procedural Three.js geometry and CanvasTexture materials.

2D GAME & CANVAS RULES (apply when building 2D games such as Subway Surfers 2D runners, arcade, platformers, or Canvas apps):
- Mount a real <canvas ref={canvasRef} className="block w-full h-full touch-none" /> ALWAYS at the root of the viewport across all screens ('title', 'playing', 'paused', 'gameover') — NEVER conditionally mount <canvas> inside {screen === 'playing' && <canvas>} where useEffect([], []) misses it!
- Keep high-frequency 60 FPS physics, lanes, player velocity, obstacles, coins, score, and input inside useRef objects driven by requestAnimationFrame(loop) with clamped dt = Math.min(rawDt, 0.05). Sync HUD numbers to React state cleanly.
- Support keyboard controls (ArrowLeft/A, ArrowRight/D to switch lanes; ArrowUp/W/Space to jump; ArrowDown/S to slide/roll; Escape/P to pause) AND pointer/touch swipe or mobile tap controls.
- On clicking "Play Game" (also Space/Enter on Title), immediately switch phaseRef.current = 'playing' and react phase state = 'playing', reset obstacles/score cleanly, and start active gameplay on the running canvas!
- Put HUD overlays in a <div className="pointer-events-none fixed inset-0 ..."> wrapper with pointer-events-auto ONLY on buttons; NEVER put backdrop-blur over the active <canvas>.

THREE.JS & 3D RULES (apply when building 3D scenes, viewers, or 3D games):
- Import * as THREE from 'three' (and optional 'three/addons/controls/OrbitControls.js' or 'three/addons/environments/RoomEnvironment.js').
- Mount renderer.domElement inside a dedicated empty <div ref={mountRef} className="w-full h-full" /> inside useEffect(..., []), handle ResizeObserver/resize, cancel animation frame and call renderer.dispose() on unmount.
- Use THREE.ACESFilmicToneMapping, PMREMGenerator + RoomEnvironment for rich metallic/PBR reflections, and a warm DirectionalLight + cool HemisphereLight fill.
- Build multi-part THREE.Group objects and procedural CanvasTextures (zero external 404 texture URLs), and never place CSS backdrop-blur over the WebGL viewport.

LIVE AI FEATURES & ACTIVE API KEY GUARANTEE:
- Mist ALREADY authenticates and configures the user's active BYOK API key on the Mist backend behind POST /api/app-ai and window.mistAI.complete() / window.mistAI.chat().
- Generated apps MUST NEVER prompt users for an API key, render an "Enter API Key" input box, or show "Missing API key" warnings!
- Do NOT add chatbots, "Ask AI" widgets, or /api/app-ai calls to standard websites, portfolios, stores, 2D Canvas games, or Three.js apps unless specifically requested or enabled in the user instructions.
- ONLY when AI features are explicitly requested or enabled in the prompt, implement real fetch('/api/app-ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt, messages, systemInstruction }) }) calls returning { text } — with real loading & error states, never setTimeout/mock stubs.`;

export function buildActiveKeyDirective(config?: AiProviderConfig): string {
  if (!config) return '';
  const providerTitle = config.name?.trim() || config.provider || 'BYOK Provider';
  const masked = maskApiKey(config.apiKey);
  if (!masked) {
    return `\nACTIVE STUDIO RUNTIME CONTEXT:\n- Active Provider/Model: ${providerTitle} (${config.model}).`;
  }
  return `\nACTIVE STUDIO API KEY CONTEXT:
- The user's active BYOK API key (${masked} on ${providerTitle} · ${config.model}) IS ALREADY CONFIGURED AND ACTIVE in Mist.
- If the app uses AI features, POST /api/app-ai (and window.mistAI) automatically authenticates requests with that configured API key via Mist's secure session relay — NEVER ask the end-user to enter an API key or hardcode any raw secret string.`;
}

function extractJsonObject(raw: string): Record<string, unknown> {
  const trimmed = raw.trim();
  const fenceMatch = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fenceMatch ? fenceMatch[1].trim() : trimmed;
  try {
    return JSON.parse(candidate) as Record<string, unknown>;
  } catch {
    const firstBrace = candidate.indexOf('{');
    const lastBrace = candidate.lastIndexOf('}');
    if (firstBrace !== -1 && lastBrace > firstBrace) {
      return JSON.parse(candidate.slice(firstBrace, lastBrace + 1)) as Record<string, unknown>;
    }
    throw new Error('Model response did not contain valid JSON.');
  }
}

function detectStreamedPaths(accumulatedText: string): string[] {
  const paths: string[] = [];
  const regex = /"path"\s*:\s*"([^"]+)"/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(accumulatedText)) !== null) {
    const clean = normalizeProjectFilePath(match[1]);
    if (!paths.includes(clean)) {
      paths.push(clean);
    }
  }
  return paths;
}

export function buildGenerateUserPrompt(
  prompt: string,
  enableAppAi: boolean,
  config?: AiProviderConfig,
): string {
  const aiCapabilityDirective = enableAppAi
    ? '\n- Interactive App AI Runtime is requested/enabled: wire real fetch(\'/api/app-ai\', { method: \'POST\', headers: { \'Content-Type\': \'application/json\' }, body: JSON.stringify({ prompt, messages, systemInstruction }) }) calls directly in the generated UI with real loading & error states.'
    : '\n- Do NOT include AI chatbots, "Ask AI" sidebars, or /api/app-ai calls — build a clean, self-contained application tailored purely to the user request.';
  const activeKeyNote = buildActiveKeyDirective(config);

  return `Build a complete, high-craft React + TypeScript + Tailwind CSS web app (or Three.js / Canvas game) for this request:
"${prompt.trim()}"${aiCapabilityDirective}${activeKeyNote}

CRITICAL OUTPUT RULES:
- "src/App.tsx" MUST be the VERY FIRST file in the "files" array and MUST default-export App (export default function App()).
- Keep architecture tight (2 to 5 well-structured files max), verify all relative imports match returned files cleanly, and complete EVERY component and handler without placeholders or truncation.
- Also include "src/index.css" starting with @import "tailwindcss";.
- Respond strictly with valid JSON matching this shape:
{
  "projectName": "Short site title",
  "description": "One-sentence summary of the site",
  "summary": "Brief note describing what you built",
  "files": [
    { "path": "src/App.tsx", "language": "tsx", "content": "..." },
    { "path": "src/components/Navbar.tsx", "language": "tsx", "content": "..." },
    { "path": "src/index.css", "language": "css", "content": "@import \\"tailwindcss\\";\\n" }
  ]
}`;
}

export function buildRefineUserPrompt(
  instruction: string,
  files: ProjectFile[],
  selectedElement?: { tagName: string; textContent: string; className: string },
  enableAppAi?: boolean,
  config?: AiProviderConfig,
): string {
  const fileBundleText = (files || [])
    .map((f) => `--- FILE: ${f.path} ---\n${f.content}`)
    .join('\n\n');

  const elementContext = selectedElement
    ? `\nFocused element selected by user: <${selectedElement.tagName}> className="${selectedElement.className}" text="${selectedElement.textContent}"`
    : '';

  const aiDirective = enableAppAi
    ? `- Wire real calls to POST /api/app-ai ({ prompt, messages, systemInstruction }) returning { text } if adding/updating live AI features — Mist's active BYOK API key backs /api/app-ai automatically (never ask the user for an API key or use setTimeout stubs).`
    : `- Do NOT introduce unrequested AI chatbots or /api/app-ai calls unless the instruction asks for them.`;
  const activeKeyNote = buildActiveKeyDirective(config);

  return `Refine the existing application according to EVERY detail in this instruction:
"${instruction.trim()}"${elementContext}${activeKeyNote}

MULTI-PART REFINEMENT MANDATE:
- Read every clause in the user's message carefully (e.g., color/palette changes, game/canvas bug fixes, speed/physics tweaks, new buttons or panels, layout changes) and apply ALL of them together in this single pass!
- If fixing a broken game or "Play Game" button: ensure <canvas> is always mounted (never hidden before effect initialization), buttons use <button type="button" onClick={...}> (never <a href="/...">), and requestAnimationFrame loop transitions cleanly into active play.
${aiDirective}

Current files:
${fileBundleText}

Return valid JSON containing ONLY the modified or newly created files (full complete file contents, never ellipses):
{
  "summary": "Concise list of every change applied",
  "files": [
    { "path": "src/App.tsx", "language": "tsx", "content": "..." }
  ]
}`;
}

export interface MistAppDeps {
  deploymentStore?: DeploymentStore;
  adminStore?: AdminDatabaseOperations;
  r2Store?: R2StorageOperations;
  edgeOriginSecret?: string;
  publishBaseUrl?: string;
  verifyAuthHeader?: (authHeader?: string) => Promise<VerifiedClerkUser>;
  aiFetchImpl?: typeof fetch;
  searchFetchImpl?: typeof fetch;
  searchService?: WebSearchService;
  notificationService?: PushNotificationService;
  skipDnsLookup?: boolean;
  trustProxy?: boolean | number | string;
  aiRateLimitMax?: number;
  catalogRateLimitMax?: number;
  deployRateLimitMax?: number;
  searchRateLimitMax?: number;
  notificationRateLimitMax?: number;
  testNotificationRateLimitMax?: number;
  bundleRateLimitMax?: number;
  renderRateLimitMax?: number;
  rateLimitAdapter?: SharedRateLimitAdapter;
  renderFetchImpl?: typeof fetch;
}

function resolveAdminStore(depsStore?: AdminDatabaseOperations): AdminDatabaseOperations {
  if (depsStore) return depsStore;
  const isProd = process.env.NODE_ENV === 'production';
  const hasCreds = Boolean(process.env.FIREBASE_SERVICE_ACCOUNT_JSON);
  if (!isProd && !hasCreds) {
    return new InMemoryAdminStore();
  }
  try {
    return new FirestoreAdminStore();
  } catch (err) {
    if (isProd) {
      throw new Error(
        `Failed to initialize production FirestoreAdminStore: ${
          err instanceof Error ? err.message : String(err)
        }. In-memory fallback is disabled in production to prevent data loss upon server restart.`
      );
    }
    return new InMemoryAdminStore();
  }
}

function resolveR2Store(depsStore?: R2StorageOperations): R2StorageOperations {
  if (depsStore) return depsStore;
  const isProd = process.env.NODE_ENV === 'production';
  const hasKey = Boolean(process.env.R2_SECRET_ACCESS_KEY);
  if (!isProd && !hasKey) {
    return new InMemoryR2ArtifactStore();
  }
  try {
    return new CloudflareR2ArtifactStore();
  } catch (err) {
    if (isProd) {
      throw new Error(
        `Failed to initialize production CloudflareR2ArtifactStore: ${
          err instanceof Error ? err.message : String(err)
        }. In-memory fallback is disabled in production to prevent data loss upon server restart.`
      );
    }
    return new InMemoryR2ArtifactStore();
  }
}

export function createMistApp(deps: MistAppDeps = {}): Express {
  const app = express();

  const publishBaseUrl = deps.publishBaseUrl ?? process.env.PUBLISH_BASE_URL?.trim();

  // Host-only cookie protection: prevents any parent-domain cookie leakage to published subdomains
  app.use(enforceHostOnlyCookies(publishBaseUrl));

  const adminStore = resolveAdminStore(deps.adminStore);
  const r2Store = resolveR2Store(deps.r2Store);

  const deploymentStore =
    deps.deploymentStore ||
    createFirestoreDeploymentStore({ adminStore, r2Store });
  const verifyAuth = deps.verifyAuthHeader || verifyClerkAuthHeader;
  const aiFetchImpl = deps.aiFetchImpl;
  const searchFetchImpl = deps.searchFetchImpl ?? deps.aiFetchImpl;
  const searchService = deps.searchService || defaultWebSearchService;
  const notificationService =
    deps.notificationService ||
    new PushNotificationService({
      store: adminStore,
    });
  const skipDnsLookup = deps.skipDnsLookup;
  const renderFetchImpl = deps.renderFetchImpl;

  const configuredTrustProxy =
    deps.trustProxy !== undefined
      ? deps.trustProxy
      : process.env.TRUST_PROXY === 'true'
        ? 1
        : process.env.TRUST_PROXY === 'loopback'
          ? 'loopback'
          : false;
  app.set('trust proxy', configuredTrustProxy);

  app.disable('x-powered-by');
  app.use((req, res, next) => {
    const hostHeader = getEffectiveHost(req);
    const pubCheck = isPublishingHostname(hostHeader, publishBaseUrl);
    (req as any).isPublishingHost = pubCheck.isPublishing;
    (req as any).publishingSlug = pubCheck.slug;

    if (pubCheck.isPublishing) {
      // Dedicated publishing hostname:
      // Block builder API and control plane endpoints
      if (req.path.startsWith('/api/') || req.path === '/sw.js') {
        res.status(404).json({ error: 'Mist API is not accessible on published website domains.' });
        return;
      }
    } else {
      // Builder hostname: apply Builder CSP and strict application security headers
      res.setHeader('Content-Security-Policy', BUILDER_CSP);
      res.setHeader('X-Content-Type-Options', 'nosniff');
      res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
      res.setHeader('Permissions-Policy', 'camera=(), geolocation=(), payment=()');
      res.setHeader('X-Frame-Options', 'SAMEORIGIN');
      res.setHeader('Cross-Origin-Opener-Policy', 'same-origin-allow-popups');
      res.setHeader('X-Permitted-Cross-Domain-Policies', 'none');
      res.setHeader('X-DNS-Prefetch-Control', 'off');
    }
    next();
  });
  app.use(createEdgeOriginSecretMiddleware({ expectedSecret: deps.edgeOriginSecret }));
  app.use(enforceSameOriginOnMutations);
  app.use(express.json({ limit: '6mb' }));
  app.use(handleBodyParserErrors);

  // Explicit health check endpoints
  app.get('/api/health', (_req, res) => {
    res.json({
      status: 'ok',
      service: 'mist-control-plane',
      time: new Date().toISOString(),
    });
  });
  app.get('/healthz', (_req, res) => {
    res.json({ status: 'ok', time: new Date().toISOString() });
  });

  const requireVerifiedAuth = createClerkAuthMiddleware({
    requireVerifiedEmail: true,
    verifyHeaderFn: verifyAuth,
  });

  const optionalAuth = createOptionalAuthMiddleware({
    verifyHeaderFn: verifyAuth,
  });

  const sharedAdapter = deps.rateLimitAdapter;

  const aiRateLimiter = createRateLimiter({
    windowMs: 60_000,
    maxRequests: deps.aiRateLimitMax ?? 60,
    label: 'AI',
    adapter: sharedAdapter,
  });
  const catalogRateLimiter = createRateLimiter({
    windowMs: 60_000,
    maxRequests: deps.catalogRateLimitMax ?? 120,
    label: 'model catalog',
    adapter: sharedAdapter,
  });
  const deployRateLimiter = createRateLimiter({
    windowMs: 60_000,
    maxRequests: deps.deployRateLimitMax ?? 30,
    label: 'deployment',
    adapter: sharedAdapter,
  });
  const searchRateLimiter = createRateLimiter({
    windowMs: 60_000,
    maxRequests: deps.searchRateLimitMax ?? 40,
    label: 'web search',
    adapter: sharedAdapter,
  });
  const notificationRateLimiter = createRateLimiter({
    windowMs: 60_000,
    maxRequests: deps.notificationRateLimitMax ?? 60,
    label: 'notifications',
    adapter: sharedAdapter,
  });
  const testNotificationRateLimiter = createRateLimiter({
    windowMs: 60_000,
    maxRequests: deps.testNotificationRateLimitMax ?? 15,
    label: 'test push notifications',
    adapter: sharedAdapter,
  });
  const bundleRateLimiter = createRateLimiter({
    windowMs: 60_000,
    maxRequests: deps.bundleRateLimitMax ?? 30,
    userMaxRequests: (deps.bundleRateLimitMax ?? 30) * 2,
    label: 'bundling',
    adapter: sharedAdapter,
  });
  const syncRateLimiter = createRateLimiter({
    windowMs: 60_000,
    maxRequests: 50,
    label: 'project synchronization',
    adapter: sharedAdapter,
  });
  const renderRateLimiter = createRateLimiter({
    windowMs: 60_000,
    maxRequests: deps.renderRateLimitMax ?? 30,
    label: 'Render',
    adapter: sharedAdapter,
  });

  const recentModelIncidents = new Map<string, ModelHealthIncident>();

  function recordIncident(incident: ModelHealthIncident) {
    if (incident.code === 'RATE_LIMIT' || incident.code === 'SERVER_OUTAGE') {
      recentModelIncidents.set(`${incident.provider}:${incident.model}`, incident);
    }
  }

  function clearIncident(provider: AiProviderId, model: string) {
    recentModelIncidents.delete(`${provider}:${model}`);
  }

  async function verifyAndAutoRepairFiles(params: {
    files: ProjectFile[];
    title: string;
    config: AiProviderConfig;
    instruction: string;
    signal?: AbortSignal;
    onPhase?: (phase: string) => void;
    maxRepairs?: number;
  }): Promise<{
    files: ProjectFile[];
    verification: ProjectVerificationResult;
    repairAttempts: number;
  }> {
    let currentFiles = params.files;
    let verification = await verifyFinalProjectState({
      files: currentFiles,
      title: params.title,
    });
    let repairAttempts = 0;
    const maxRepairs = params.maxRepairs ?? 2;

    while (!verification.buildOk && verification.bundleError && repairAttempts < maxRepairs) {
      if (params.signal?.aborted) break;
      repairAttempts += 1;
      params.onPhase?.(`Build error detected — repairing automatically (attempt ${repairAttempts}/${maxRepairs})...`);

      const filesSnapshot = currentFiles
        .map((f) => `--- ${f.path} ---\n${f.content.slice(0, 6000)}`)
        .join('\n\n');

      const repairPrompt = `Your generated React + TypeScript project failed esbuild verification with this EXACT build error:
${verification.bundleError}

Original user goal: "${params.instruction.trim()}"

RULES TO FIX THIS:
- Allowed imports ONLY: 'react', 'react-dom/client', 'lucide-react', 'three', 'three/addons/*', and local relative files in your returned "files" array.
- If the error mentions '@react-three/fiber' or '@react-three/drei' or any missing package ("mist-missing:..."), rewrite the 3D scene using pure 'three' (import * as THREE from 'three') mounted inside a <div ref={mountRef} /> with useEffect and requestAnimationFrame.
- Fix any broken relative imports, missing exports, or TypeScript/JSX syntax errors.
- Keep "src/App.tsx" as default export and ensure "src/index.css" starts with @import "tailwindcss";.

Current project files:
${filesSnapshot}

Return ONLY valid JSON: { "summary": "Brief description of fix", "files": [{ "path": string, "language": string, "content": string }] }`;

      try {
        const repairRaw = await callByokCompletionRaw({
          config: params.config,
          messages: [
            { role: 'system', content: `${SYSTEM_GENERATOR_PROMPT}\nRespond strictly with valid JSON.` },
            { role: 'user', content: repairPrompt },
          ],
          jsonMode: true,
          maxTokens: 12288,
          signal: params.signal,
          fetchImpl: aiFetchImpl,
          skipDnsLookup,
        });
        const repairedObj = extractJsonObject(repairRaw);
        if (Array.isArray(repairedObj.files) && repairedObj.files.length > 0) {
          const repairedValidated = validateProjectFilesPayload(
            repairedObj.files.map((f) => {
              const entry = (f || {}) as { path?: string; language?: string; content?: string };
              return {
                path: entry.path || 'src/App.tsx',
                language: entry.language,
                content: String(entry.content || ''),
              };
            }),
          );
          currentFiles = mergeProjectFiles(currentFiles, repairedValidated);
          if (!currentFiles.some((f) => f.path.toLowerCase() === 'src/index.css')) {
            currentFiles.push({
              id: 'file_index_css',
              path: 'src/index.css',
              language: 'css',
              content: '@import "tailwindcss";\n',
            });
          }
          verification = await verifyFinalProjectState({
            files: currentFiles,
            title: params.title,
          });
        } else {
          break;
        }
      } catch {
        break;
      }
    }

    return { files: currentFiles, verification, repairAttempts };
  }

  async function verifyRefinementResult(params: {
    inputFiles: ProjectFile[];
    refinedRawFiles: Array<{ path: string; language?: ProjectFile['language']; content: string }>;
    title: string;
    config: AiProviderConfig;
    instruction: string;
    signal?: AbortSignal;
    onPhase?: (phase: string) => void;
  }): Promise<{
    files: ProjectFile[];
    verification: ProjectVerificationResult;
    repairAttempts: number;
  }> {
    const validatedRefined = validateProjectFilesPayload(params.refinedRawFiles);
    const mergedForVerification = mergeProjectFiles(params.inputFiles, validatedRefined);
    if (!mergedForVerification.some((f) => f.path.toLowerCase() === 'src/index.css')) {
      mergedForVerification.push({
        id: 'file_index_css',
        path: 'src/index.css',
        language: 'css',
        content: '@import "tailwindcss";\n',
      });
    }
    const verified = await verifyAndAutoRepairFiles({
      files: mergedForVerification,
      title: params.title,
      config: params.config,
      instruction: params.instruction,
      signal: params.signal,
      onPhase: params.onPhase,
    });
    const inputByPath = new Map(
      params.inputFiles.map((f) => [normalizeProjectFilePath(f.path), f.content]),
    );
    const refinedPathSet = new Set(validatedRefined.map((f) => normalizeProjectFilePath(f.path)));
    const deltaFiles = verified.files.filter((f) => {
      const cleanPath = normalizeProjectFilePath(f.path);
      return refinedPathSet.has(cleanPath) || inputByPath.get(cleanPath) !== f.content;
    });
    return {
      files: deltaFiles.length > 0 ? deltaFiles : validatedRefined,
      verification: verified.verification,
      repairAttempts: verified.repairAttempts,
    };
  }

  async function postProcessGeneratedProject(params: {
    parsed: Record<string, unknown>;
    prompt: string;
    config: AiProviderConfig;
    signal?: AbortSignal;
    onPhase?: (phase: string) => void;
  }): Promise<Record<string, unknown>> {
    const { parsed, prompt, config } = params;
    const rawFiles = Array.isArray(parsed.files) ? parsed.files : [];
    let validatedFiles = validateProjectFilesPayload(
      rawFiles.map((f) => {
        const entry = (f || {}) as { path?: string; language?: string; content?: string };
        return {
          path: entry.path || 'src/App.tsx',
          language: entry.language,
          content: String(entry.content || ''),
        };
      }),
    );

    const hasRootApp = validatedFiles.some((f) => {
      const lower = f.path.toLowerCase();
      return lower === 'src/app.tsx' || lower === 'src/app.jsx' || lower === 'app.tsx' || lower === 'app.jsx';
    });

    if (!hasRootApp && validatedFiles.length > 0) {
      const existingSummary = validatedFiles
        .map((f) => `--- ${f.path} ---\n${f.content.slice(0, 1800)}`)
        .join('\n\n');
      const repairPrompt = `You generated files for "${prompt.trim()}" but omitted src/App.tsx.
Write the complete root "src/App.tsx" (default-exported function App) that composes the generated components cleanly with full responsive UI and working state.

Existing generated files:
${existingSummary}

Return JSON: { "content": "..." }`;

      let synthesizedAppContent = '';
      try {
        const repairRaw = await callByokCompletionRaw({
          config,
          messages: [
            { role: 'system', content: `${SYSTEM_GENERATOR_PROMPT}\nRespond strictly with valid JSON.` },
            { role: 'user', content: repairPrompt },
          ],
          jsonMode: true,
          maxTokens: 6144,
          fetchImpl: aiFetchImpl,
          skipDnsLookup,
        });
        const repairJson = extractJsonObject(repairRaw);
        if (typeof repairJson.content === 'string' && repairJson.content.trim()) {
          synthesizedAppContent = repairJson.content;
        }
      } catch {
        // Fallback below guarantees valid src/App.tsx
      }

      if (!synthesizedAppContent) {
        const firstComp = validatedFiles.find((f) => f.path.endsWith('.tsx'));
        if (firstComp) {
          const rel = './' + firstComp.path.replace(/^src\//, '').replace(/\.tsx$/, '');
          synthesizedAppContent = `import React from 'react';\nimport PrimaryView from '${rel}';\n\nexport default function App() {\n  return <PrimaryView />;\n}\n`;
        }
      }

      if (synthesizedAppContent) {
        validatedFiles = validateProjectFilesPayload([
          { path: 'src/App.tsx', language: 'tsx', content: synthesizedAppContent },
          ...validatedFiles,
        ]);
      }
    }

    if (!validatedFiles.some((f) => f.path.toLowerCase() === 'src/index.css')) {
      validatedFiles.push({
        id: 'file_index_css',
        path: 'src/index.css',
        language: 'css',
        content: '@import "tailwindcss";\n',
      });
    }

    parsed.files = validatedFiles;
    if (!parsed.projectName && typeof parsed.title === 'string') {
      parsed.projectName = parsed.title;
    }

    // Run build verification AFTER all post-generation file additions/repairs are complete,
    // and auto-repair any esbuild/missing-module errors before returning.
    const verifiedResult = await verifyAndAutoRepairFiles({
      files: validatedFiles,
      title: typeof parsed.projectName === 'string' ? parsed.projectName : 'Mist Preview',
      config,
      instruction: prompt,
      signal: params.signal,
      onPhase: params.onPhase,
    });
    parsed.files = verifiedResult.files;
    parsed.verification = verifiedResult.verification;
    if (verifiedResult.repairAttempts > 0) {
      parsed.repairAttempts = verifiedResult.repairAttempts;
    }
    return parsed;
  }

  app.get('/vendor/preview-runtime.js', async (_req, res) => {
    try {
      const bundle = await ensureVendorRuntime();
      res.setHeader('Content-Type', 'application/javascript; charset=utf-8');
      res.setHeader('Cache-Control', 'public, max-age=3600');
      res.send(bundle);
    } catch (err) {
      const safeMsg = sanitizeErrorMessage(err);
      res.status(500).send(`console.error("Failed to build vendor runtime: ${safeMsg}");`);
    }
  });

  app.post(
    '/api/bundle',
    optionalAuth,
    bundleRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.BUNDLE, 'Bundle request'),
    async (req, res) => {
      try {
        const { files, title, includeInspector, enableAppAi, standaloneExport } = req.body as {
          files: ProjectFile[];
          title?: string;
          includeInspector?: boolean;
          enableAppAi?: boolean;
          standaloneExport?: boolean;
        };
        const validatedFiles = validateProjectFilesPayload(files);
        const isStandalone = Boolean(standaloneExport);

        const bundlePromise = bundleProjectToHtml({
          files: validatedFiles,
          title: (title || 'Mist Preview').slice(0, 120),
          includeInspector: isStandalone ? false : includeInspector !== false,
          enableAppAi: isStandalone ? false : Boolean(enableAppAi),
          standaloneExport: isStandalone,
        });

        const timeoutPromise = new Promise<{ html: string; bundleError?: string }>((_, reject) =>
          setTimeout(() => reject(new SecurityValidationError(504, 'Bundling operation timed out after 30s.')), 30_000),
        );

        const result = await Promise.race([bundlePromise, timeoutPromise]);
        res.json(result);
      } catch (err) {
        sendSecurityErrorResponse(res, err, 500);
      }
    },
  );

  app.get('/api/ai/status', (_req, res) => {
    res.json({
      byokOnly: true,
      incidents: Array.from(recentModelIncidents.values()),
    });
  });

  // Public unauthenticated catalog GET ONLY for public OpenRouter catalog without API keys.
  // Any custom baseUrl or keyed lookup requires authenticated POST /api/ai/models.
  app.get('/api/ai/models', catalogRateLimiter, async (req, res) => {
    const baseUrl =
      typeof req.query.baseUrl === 'string' && req.query.baseUrl.trim()
        ? req.query.baseUrl.trim()
        : 'https://openrouter.ai/api/v1';
    const forceRefresh = req.query.forceRefresh === 'true';

    if (detectGatewayFromBaseUrl(baseUrl) !== 'openrouter') {
      res.status(401).json({
        error: 'Sign in to Mist to inspect models on non-public gateways.',
      });
      return;
    }

    try {
      const result = await fetchGatewayModelsCatalog({
        baseUrl: 'https://openrouter.ai/api/v1',
        forceRefresh,
        fetchImpl: aiFetchImpl,
        skipDnsLookup,
      });
      res.json(result);
    } catch (err) {
      const status = err instanceof SecurityValidationError ? err.status : 502;
      res.status(status).json({ error: sanitizeErrorMessage(err) });
    }
  });

  // Authenticated gateway catalog lookup (Groq, Gemini BYOK, NVIDIA, OpenAI, Custom endpoints)
  app.post(
    '/api/ai/models',
    requireVerifiedAuth,
    catalogRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.AI_CONFIG, 'Catalog request'),
    async (req: AuthenticatedRequest, res) => {
      const { baseUrl, apiKey, forceRefresh } = req.body as {
        baseUrl?: string;
        apiKey?: string;
        forceRefresh?: boolean;
      };
      const targetUrl = (baseUrl || 'https://openrouter.ai/api/v1').trim();
      try {
        validateExternalUrlSyntax(targetUrl);
        const result = await fetchGatewayModelsCatalog({
          baseUrl: targetUrl,
          apiKey,
          forceRefresh: Boolean(forceRefresh),
          fetchImpl: aiFetchImpl,
          skipDnsLookup,
        });
        res.json(result);
      } catch (err) {
        sendSecurityErrorResponse(res, err, 502);
      }
    },
  );

  // Account-bound encrypted BYOK credential vault seal & unseal routes
  app.post(
    '/api/user/vault/seal',
    requireVerifiedAuth,
    catalogRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.VAULT, 'Vault request'),
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        if (!user.email) {
          res.status(400).json({ error: 'An account email is required to seal credentials.' });
          return;
        }
        const { aiConfig, searchConfig } = req.body as {
          aiConfig?: AiProviderConfig;
          searchConfig?: WebSearchConfig;
        };
        const validated = validateVaultPayload({
          aiConfig: aiConfig ? normalizeProviderConfigToStudio(aiConfig) : undefined,
          searchConfig: searchConfig ? normalizeWebSearchConfig(searchConfig) : undefined,
        });
        const sealed = sealUserVaultPayload({
          uid: user.userId,
          email: user.email,
          aiConfig: validated.aiConfig,
          searchConfig: validated.searchConfig,
        });
        await adminStore.saveUserVault(user.userId, user.email, {
          ciphertext: sealed.encryptedPayload,
          aiKeyHint: sealed.aiKeyHint,
          searchKeyHint: sealed.searchKeyHint,
        });
        res.json(sealed);
      } catch (err) {
        sendSecurityErrorResponse(res, err, 400);
      }
    },
  );

  app.post(
    '/api/user/vault/unseal',
    requireVerifiedAuth,
    catalogRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.VAULT, 'Vault request'),
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        if (!user.email) {
          res.status(400).json({ error: 'An account email is required to unseal credentials.' });
          return;
        }
        let encryptedPayload = (req.body as { encryptedPayload?: string })?.encryptedPayload;
        if (!encryptedPayload) {
          const vaultDoc = await adminStore.getUserVault(user.userId);
          encryptedPayload = vaultDoc?.ciphertext;
        }
        if (!encryptedPayload) {
          res.status(404).json({ error: 'No encrypted credentials found in vault.' });
          return;
        }
        const unsealed = unsealUserVaultPayload({
          uid: user.userId,
          email: user.email,
          encryptedPayload,
        });

        // Key rotation & migration: if decrypted with a previous key or legacy fallback, seamlessly re-encrypt
        if (unsealed.needsReencryption) {
          try {
            const resealed = sealUserVaultPayload({
              uid: user.userId,
              email: user.email,
              aiConfig: unsealed.aiConfig,
              searchConfig: unsealed.searchConfig,
            });
            await adminStore.saveUserVault(user.userId, user.email, {
              ciphertext: resealed.encryptedPayload,
              aiKeyHint: resealed.aiKeyHint,
              searchKeyHint: resealed.searchKeyHint,
            });
          } catch (reencryptErr) {
            console.warn('[Mist Vault] Silent re-encryption update skipped:', sanitizeErrorMessage(reencryptErr));
          }
        }

        res.json({
          aiConfig: unsealed.aiConfig ? normalizeProviderConfigToStudio(unsealed.aiConfig) : undefined,
          searchConfig: unsealed.searchConfig
            ? normalizeWebSearchConfig(unsealed.searchConfig)
            : undefined,
        });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 403;
        res.status(status).json({ error: sanitizeErrorMessage(err) || 'Failed to unseal credential vault.' });
      }
    },
  );

  app.get(
    '/api/user/vault',
    requireVerifiedAuth,
    catalogRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        const vault = await adminStore.getUserVault(user.userId);
        res.json({ vault });
      } catch (err) {
        res.status(500).json({ error: sanitizeErrorMessage(err) });
      }
    },
  );

  app.delete(
    '/api/user/vault',
    requireVerifiedAuth,
    catalogRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        await adminStore.deleteUserVault(user.userId);
        res.json({ success: true });
      } catch (err) {
        res.status(500).json({ error: sanitizeErrorMessage(err) });
      }
    },
  );

  // --- Real Connect to Render Integration Endpoints ---

  app.post(
    '/api/render/connect',
    requireVerifiedAuth,
    renderRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.VAULT, 'Render connect request'),
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        if (!user.email) {
          res.status(400).json({ error: 'An account email is required to connect Render.' });
          return;
        }
        const { apiKey } = req.body as { apiKey?: string };
        const validatedKey = validateRenderApiKey(apiKey);

        // Verify key against official Render API (GET /v1/owners)
        const verification = await verifyRenderApiKey(validatedKey, {
          fetchImpl: renderFetchImpl,
        });

        // Unseal existing vault if present to preserve AI & search configs
        const vaultDoc = await adminStore.getUserVault(user.userId);
        let unsealed: VaultPlainPayload = {};
        if (vaultDoc?.ciphertext) {
          try {
            unsealed = unsealUserVaultPayload({
              uid: user.userId,
              email: user.email,
              encryptedPayload: vaultDoc.ciphertext,
            });
          } catch {
            // Start clean if existing ciphertext was invalid
          }
        }

        const renderConfig: RenderCredentialConfig = {
          apiKey: validatedKey,
          ownerId: verification.primaryOwner.id,
          ownerName: verification.primaryOwner.name,
          ownerEmail: verification.primaryOwner.email,
          workspaceType: verification.primaryOwner.type,
          connectedAt: new Date().toISOString(),
        };

        const sealed = sealUserVaultPayload({
          uid: user.userId,
          email: user.email,
          aiConfig: unsealed.aiConfig,
          searchConfig: unsealed.searchConfig,
          renderConfig,
        });

        await adminStore.saveUserVault(user.userId, user.email, {
          ciphertext: sealed.encryptedPayload,
          aiKeyHint: sealed.aiKeyHint,
          searchKeyHint: sealed.searchKeyHint,
          renderKeyHint: sealed.renderKeyHint,
        });

        res.json({
          ok: true,
          connected: true,
          owner: verification.primaryOwner,
          workspaces: verification.owners,
          keyHint: sealed.renderKeyHint,
          connectedAt: renderConfig.connectedAt,
        });
      } catch (err) {
        sendSecurityErrorResponse(res, err, 400);
      }
    },
  );

  app.get(
    '/api/render/status',
    requireVerifiedAuth,
    renderRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        if (!user.email) {
          res.json({ connected: false });
          return;
        }
        const vaultDoc = await adminStore.getUserVault(user.userId);
        if (!vaultDoc?.ciphertext) {
          res.json({ connected: false });
          return;
        }
        let unsealed: VaultPlainPayload;
        try {
          unsealed = unsealUserVaultPayload({
            uid: user.userId,
            email: user.email,
            encryptedPayload: vaultDoc.ciphertext,
          });
        } catch {
          res.json({ connected: false });
          return;
        }

        if (!unsealed.renderConfig || !unsealed.renderConfig.apiKey) {
          res.json({ connected: false });
          return;
        }

        res.json({
          connected: true,
          owner: {
            id: unsealed.renderConfig.ownerId,
            name: unsealed.renderConfig.ownerName,
            email: unsealed.renderConfig.ownerEmail,
            type: unsealed.renderConfig.workspaceType || 'user',
          },
          ownerId: unsealed.renderConfig.ownerId,
          ownerName: unsealed.renderConfig.ownerName,
          ownerEmail: unsealed.renderConfig.ownerEmail,
          workspaceType: unsealed.renderConfig.workspaceType || 'user',
          keyHint: maskApiKey(unsealed.renderConfig.apiKey),
          connectedAt: unsealed.renderConfig.connectedAt,
        });
      } catch (err) {
        res.status(500).json({ error: sanitizeErrorMessage(err) });
      }
    },
  );

  app.post(
    '/api/render/disconnect',
    requireVerifiedAuth,
    renderRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        if (!user.email) {
          res.status(400).json({ error: 'An account email is required.' });
          return;
        }
        const vaultDoc = await adminStore.getUserVault(user.userId);
        if (!vaultDoc?.ciphertext) {
          res.json({ ok: true, connected: false });
          return;
        }
        const unsealed = unsealUserVaultPayload({
          uid: user.userId,
          email: user.email,
          encryptedPayload: vaultDoc.ciphertext,
        });

        const sealed = sealUserVaultPayload({
          uid: user.userId,
          email: user.email,
          aiConfig: unsealed.aiConfig,
          searchConfig: unsealed.searchConfig,
          renderConfig: undefined,
        });

        await adminStore.saveUserVault(user.userId, user.email, {
          ciphertext: sealed.encryptedPayload,
          aiKeyHint: sealed.aiKeyHint,
          searchKeyHint: sealed.searchKeyHint,
          renderKeyHint: '',
        });

        res.json({ ok: true, connected: false });
      } catch (err) {
        sendSecurityErrorResponse(res, err, 400);
      }
    },
  );

  app.get(
    '/api/render/workspaces',
    requireVerifiedAuth,
    renderRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        if (!user.email) {
          res.status(400).json({ error: 'An account email is required.' });
          return;
        }
        const vaultDoc = await adminStore.getUserVault(user.userId);
        if (!vaultDoc?.ciphertext) {
          res.status(400).json({ error: 'Render account is not connected.' });
          return;
        }
        const unsealed = unsealUserVaultPayload({
          uid: user.userId,
          email: user.email,
          encryptedPayload: vaultDoc.ciphertext,
        });
        if (!unsealed.renderConfig?.apiKey) {
          res.status(400).json({ error: 'Render account is not connected.' });
          return;
        }

        const verification = await verifyRenderApiKey(unsealed.renderConfig.apiKey, {
          fetchImpl: renderFetchImpl,
        });
        res.json({
          primaryOwner: verification.primaryOwner,
          workspaces: verification.owners,
        });
      } catch (err) {
        sendSecurityErrorResponse(res, err, 400);
      }
    },
  );

  app.post(
    '/api/render/deploy',
    requireVerifiedAuth,
    renderRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.AI_CONFIG, 'Render deploy request'),
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        if (!user.email) {
          res.status(400).json({ error: 'An account email is required.' });
          return;
        }
        const vaultDoc = await adminStore.getUserVault(user.userId);
        if (!vaultDoc?.ciphertext) {
          res.status(400).json({ error: 'Render account is not connected. Connect your Render API key first.' });
          return;
        }
        const unsealed = unsealUserVaultPayload({
          uid: user.userId,
          email: user.email,
          encryptedPayload: vaultDoc.ciphertext,
        });
        if (!unsealed.renderConfig?.apiKey) {
          res.status(400).json({ error: 'Render account is not connected. Connect your Render API key first.' });
          return;
        }

        const { repoUrl, branch, serviceName, ownerId, buildCommand, publishPath, autoDeploy } = req.body || {};
        const targetOwnerId = (ownerId || unsealed.renderConfig.ownerId || '').trim();

        const service = await createRenderStaticSite(
          unsealed.renderConfig.apiKey,
          {
            name: serviceName || 'mist-site',
            ownerId: targetOwnerId,
            repo: repoUrl,
            branch: branch || 'main',
            buildCommand: buildCommand || 'npm run build',
            publishPath: publishPath || 'dist',
            autoDeploy: autoDeploy || 'commit',
          },
          { fetchImpl: renderFetchImpl },
        );

        let deployInfo: { id: string; status: string } | null = null;
        try {
          deployInfo = await triggerRenderDeploy(unsealed.renderConfig.apiKey, service.id, {
            fetchImpl: renderFetchImpl,
          });
        } catch {
          // Render auto-triggers initial deploy on static site creation
        }

        // Notify user via Web Push if configured
        notificationService
          .sendNotificationToUser(user.userId, {
            title: 'Render Deployment Initiated! 🚀',
            body: `Service "${service.name}" is building on Render at ${service.url}`,
            data: { url: service.url },
            tag: `render-${service.id}`,
          })
          .catch((notifyErr) => {
            console.warn('[Mist Notifications] Render deploy push notice failed:', notifyErr);
          });

        res.json({
          ok: true,
          service,
          deploy: deployInfo,
        });
      } catch (err) {
        sendSecurityErrorResponse(res, err, 400);
      }
    },
  );

  app.get(
    '/api/render/services/:serviceId',
    requireVerifiedAuth,
    renderRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        if (!user.email) {
          res.status(400).json({ error: 'An account email is required.' });
          return;
        }
        const vaultDoc = await adminStore.getUserVault(user.userId);
        if (!vaultDoc?.ciphertext) {
          res.status(400).json({ error: 'Render account is not connected.' });
          return;
        }
        const unsealed = unsealUserVaultPayload({
          uid: user.userId,
          email: user.email,
          encryptedPayload: vaultDoc.ciphertext,
        });
        if (!unsealed.renderConfig?.apiKey) {
          res.status(400).json({ error: 'Render account is not connected.' });
          return;
        }

        const serviceId = req.params.serviceId;
        const service = await getRenderService(unsealed.renderConfig.apiKey, serviceId, {
          fetchImpl: renderFetchImpl,
        });
        const latestDeploy = await getRenderLatestDeploy(unsealed.renderConfig.apiKey, serviceId, {
          fetchImpl: renderFetchImpl,
        });

        res.json({
          ok: true,
          service,
          latestDeploy,
        });
      } catch (err) {
        sendSecurityErrorResponse(res, err, 400);
      }
    },
  );

  app.get(
    '/api/render/services',
    requireVerifiedAuth,
    renderRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        if (!user.email) {
          res.status(400).json({ error: 'An account email is required.' });
          return;
        }
        const vaultDoc = await adminStore.getUserVault(user.userId);
        if (!vaultDoc?.ciphertext) {
          res.status(400).json({ error: 'Render account is not connected.' });
          return;
        }
        const unsealed = unsealUserVaultPayload({
          uid: user.userId,
          email: user.email,
          encryptedPayload: vaultDoc.ciphertext,
        });
        if (!unsealed.renderConfig?.apiKey) {
          res.status(400).json({ error: 'Render account is not connected.' });
          return;
        }

        const services = await listRenderStaticSites(unsealed.renderConfig.apiKey, {
          fetchImpl: renderFetchImpl,
        });
        res.json({ services });
      } catch (err) {
        sendSecurityErrorResponse(res, err, 400);
      }
    },
  );

  // User Profile Preferences
  app.get(
    '/api/user/preferences',
    requireVerifiedAuth,
    catalogRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        const preferences = await adminStore.getUserPreferences(user.userId);
        res.json({ preferences: preferences || {} });
      } catch (err) {
        res.status(500).json({ error: sanitizeErrorMessage(err) });
      }
    },
  );

  app.put(
    '/api/user/preferences',
    requireVerifiedAuth,
    catalogRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        const { preferences, meta } = req.body || {};
        await adminStore.saveUserPreferences(user.userId, preferences || {}, meta);
        res.json({ success: true });
      } catch (err) {
        res.status(500).json({ error: sanitizeErrorMessage(err) });
      }
    },
  );

  // User Projects CRUD
  app.get(
    '/api/projects',
    requireVerifiedAuth,
    catalogRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        const projects = await adminStore.listUserProjects(user.userId);
        res.json({ projects });
      } catch (err) {
        res.status(500).json({ error: sanitizeErrorMessage(err) });
      }
    },
  );

  app.get(
    '/api/projects/:id',
    requireVerifiedAuth,
    catalogRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        const project = await adminStore.getProject(user.userId, req.params.id);
        if (!project) {
          res.status(404).json({ error: 'Project not found.' });
          return;
        }
        res.json({ project });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 500;
        res.status(status).json({ error: sanitizeErrorMessage(err) });
      }
    },
  );

  app.post(
    '/api/projects',
    requireVerifiedAuth,
    catalogRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        const validated = validateProjectPayload(req.body?.project);
        await adminStore.saveProject(user.userId, validated, { isNew: true });
        res.status(201).json({ success: true, project: validated });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 500;
        res.status(status).json({ success: false, error: sanitizeErrorMessage(err) });
      }
    },
  );

  app.put(
    '/api/projects/:id',
    requireVerifiedAuth,
    catalogRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        const raw = req.body?.project;
        if (!raw || typeof raw !== 'object') {
          res.status(400).json({ success: false, error: 'Valid project data is required.' });
          return;
        }
        (raw as any).id = req.params.id;
        const validated = validateProjectPayload(raw);
        await adminStore.saveProject(user.userId, validated);
        res.json({ success: true, project: validated });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 500;
        res.status(status).json({ success: false, error: sanitizeErrorMessage(err) });
      }
    },
  );

  app.delete(
    '/api/projects/:id',
    requireVerifiedAuth,
    catalogRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        await adminStore.deleteProject(user.userId, req.params.id);
        res.json({ success: true });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 500;
        res.status(status).json({ error: sanitizeErrorMessage(err) });
      }
    },
  );

  app.post(
    '/api/projects/sync',
    requireVerifiedAuth,
    syncRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.PROJECT_SYNC, 'Sync request'),
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        const rawProjects = Array.isArray(req.body?.projects) ? req.body.projects : [];
        if (rawProjects.length > 50) {
          res.status(400).json({
            success: false,
            error: 'Sync batch exceeds maximum allowed projects (50).',
          });
          return;
        }

        const validatedProjects: MistProject[] = [];
        const failedProjects: Array<{ id: string; error: string }> = [];

        for (const raw of rawProjects) {
          try {
            validatedProjects.push(validateProjectPayload(raw));
          } catch (valErr) {
            failedProjects.push({
              id: String((raw as any)?.id || 'unknown'),
              error: sanitizeErrorMessage(valErr) || 'Invalid project payload',
            });
          }
        }

        const result = await adminStore.syncProjects(user.userId, validatedProjects);
        const combinedFailed = [...failedProjects, ...result.failedProjects];
        const allSucceeded = combinedFailed.length === 0;

        res.status(allSucceeded ? 200 : (result.synced > 0 ? 207 : 400)).json({
          success: allSucceeded,
          synced: result.synced,
          successfulProjectIds: result.successfulProjectIds,
          failedProjects: combinedFailed,
        });
      } catch (err) {
        res.status(500).json({ success: false, error: sanitizeErrorMessage(err) });
      }
    },
  );


  // Ephemeral owner-bound preview AI session endpoints
  app.post(
    '/api/ai/session',
    requireVerifiedAuth,
    aiRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.AI_SESSION, 'Session request'),
    async (req: AuthenticatedRequest, res) => {
      try {
        const { providerConfig } = req.body as { providerConfig?: AiProviderConfig };
        const validatedConfig = providerConfig ? validateAiProviderConfig(providerConfig) : undefined;
        const { config } = await resolveByokRequestParams(validatedConfig, { skipDnsLookup });
        const session = createPreviewAiSession(config, req.authUser?.uid);
        res.json(session);
      } catch (err) {
        sendSecurityErrorResponse(res, err, getHttpStatusFromError(err));
      }
    },
  );

  app.post(
    '/api/ai/session/revoke-all',
    requireVerifiedAuth,
    (req: AuthenticatedRequest, res) => {
      const revokedCount = revokeAllUserPreviewSessions(req.authUser?.uid);
      res.json({ ok: true, revokedCount });
    },
  );

  app.delete(
    '/api/ai/session/:token',
    requireVerifiedAuth,
    (req: AuthenticatedRequest, res) => {
      try {
        const revoked = revokePreviewAiSession(req.params.token, req.authUser?.uid);
        res.json({ ok: true, revoked });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 403;
        res.status(status).json({ error: sanitizeErrorMessage(err) });
      }
    },
  );

  // Live verification of selected provider + model & capability probe
  app.post(
    '/api/ai/test-provider',
    requireVerifiedAuth,
    aiRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.AI_CONFIG, 'Provider test request'),
    async (req: AuthenticatedRequest, res) => {
      let validatedRaw: AiProviderConfig;
      try {
        validatedRaw = validateAiProviderConfig(req.body);
      } catch (valErr) {
        sendSecurityErrorResponse(res, valErr, 400);
        return;
      }
      const config = normalizeProviderConfigToStudio(validatedRaw);
      const provider = config.provider;
      const model = config.model;
      const abortController = new AbortController();
      res.on('close', () => {
        if (!res.writableEnded) abortController.abort();
      });

      try {
        const probed = await probeProviderCapabilities(config, {
          fetchImpl: aiFetchImpl,
          skipDnsLookup,
          signal: abortController.signal,
        });
        clearIncident(provider, model);
        res.json({
          ok: true,
          verified: true,
          testedAt: new Date().toISOString(),
          capabilities: probed,
          provider,
          model,
          name: config.name,
        });
      } catch (err) {
        const status = getHttpStatusFromError(err);
        const message = sanitizeErrorMessage(err);
        const incident = classifyModelError({ status, message, provider, model });
        recordIncident(incident);
        res.status(status).json({ ok: false, verified: false, error: incident.message, incident });
      }
    },
  );

  // Independent Web Search BYOK endpoints (never shared with preview iframes or generated apps)
  app.post(
    '/api/search',
    requireVerifiedAuth,
    searchRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.SEARCH, 'Search request'),
    async (req: AuthenticatedRequest, res) => {
      const { query, queries, searchConfig } = req.body as {
        query?: string;
        queries?: string[];
        searchConfig?: WebSearchConfig;
      };
      const queryList = Array.isArray(queries) && queries.length > 0
        ? queries.map((q) => String(q || '').trim()).filter(Boolean)
        : query && query.trim()
          ? [query.trim()]
          : [];

      if (queryList.length === 0) {
        res.status(400).json({ error: 'Provide a non-empty search query.' });
        return;
      }

      // Check max search queries per request
      if (queryList.length > 5) {
        res.status(400).json({ error: 'Exceeded maximum of 5 search queries per request.' });
        return;
      }

      let validatedSearchConfig: WebSearchConfig | undefined;
      if (searchConfig) {
        try {
          validatedSearchConfig = validateWebSearchConfig(searchConfig);
        } catch (valErr) {
          sendSecurityErrorResponse(res, valErr, 400);
          return;
        }
      }

      const abortController = new AbortController();
      res.on('close', () => {
        if (!res.writableEnded) abortController.abort();
      });

      try {
        const { outcome } = await searchService.search({
          rawConfig: validatedSearchConfig || searchConfig,
          queries: queryList,
          signal: abortController.signal,
          fetchImpl: searchFetchImpl,
          skipDnsLookup,
        });
        res.json(outcome);
      } catch (err) {
        if (err instanceof WebSearchError) {
          if (err.retryAfterSeconds) {
            res.setHeader('Retry-After', String(err.retryAfterSeconds));
          }
          res.status(err.status).json({ error: err.message, code: err.code });
          return;
        }
        sendSecurityErrorResponse(res, err, getHttpStatusFromError(err));
      }
    },
  );

  app.post(
    '/api/search/test',
    requireVerifiedAuth,
    searchRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.SEARCH, 'Search test request'),
    async (req: AuthenticatedRequest, res) => {
      const { searchConfig } = req.body as { searchConfig?: WebSearchConfig };
      let validatedSearchConfig: WebSearchConfig | undefined;
      if (searchConfig) {
        try {
          validatedSearchConfig = validateWebSearchConfig(searchConfig);
        } catch (valErr) {
          sendSecurityErrorResponse(res, valErr, 400);
          return;
        }
      }
      const abortController = new AbortController();
      res.on('close', () => {
        if (!res.writableEnded) abortController.abort();
      });

      try {
        const normalizedSearchCfg = normalizeWebSearchConfig(validatedSearchConfig || searchConfig);
        const testQuery =
          normalizedSearchCfg.provider === 'duckduckgo'
            ? 'typescript'
            : 'latest web standards specification';
        const { outcome } = await searchService.search({
          rawConfig: normalizedSearchCfg,
          queries: [testQuery],
          maxRequestsInTurn: 1,
          signal: abortController.signal,
          fetchImpl: searchFetchImpl,
          skipDnsLookup,
        });
        res.json({
          ok: true,
          verified: true,
          providerName: outcome.providerName,
          resultCount: outcome.sources.length,
          testedAt: outcome.searchedAt || new Date().toISOString(),
        });
      } catch (err) {
        if (err instanceof WebSearchError) {
          if (err.retryAfterSeconds) {
            res.setHeader('Retry-After', String(err.retryAfterSeconds));
          }
          res.status(err.status).json({ ok: false, verified: false, error: err.message, code: err.code });
          return;
        }
        const status = getHttpStatusFromError(err);
        res.status(status).json({
          ok: false,
          verified: false,
          error: sanitizeErrorMessage(err) || 'Search connection test failed.',
        });
      }
    },
  );

  async function runGroundedModelCall(params: {
    queryText: string;
    searchMode?: WebSearchMode;
    searchConfig?: WebSearchConfig;
    config: AiProviderConfig;
    baseUserPrompt: string;
    signal: AbortSignal;
    stream: boolean;
    onDelta?: (accumulated: string) => void;
    onSearchEvent?: (event: Record<string, unknown>) => void;
  }): Promise<{ parsed: Record<string, unknown>; searchOutcome: WebSearchOutcome }> {
    const decision = needsWebSearch(params.queryText, params.searchMode || 'auto');
    let searchOutcome: WebSearchOutcome = {
      status: 'skipped',
      queries: [],
      sources: [],
    };
    let searchRequestsUsed = 0;
    let searchContextSection = '';

    if (decision.shouldSearch) {
      const initialQuery = params.queryText.trim().slice(0, 240);
      params.onSearchEvent?.({
        type: 'search_start',
        queries: [initialQuery],
        phase: 'Searching the web for current context...',
      });

      try {
        const resSearch = await searchService.search({
          rawConfig: params.searchConfig,
          queries: [initialQuery],
          maxRequestsInTurn: MAX_SEARCH_REQUESTS_PER_INTERACTION,
          signal: params.signal,
          fetchImpl: searchFetchImpl,
          skipDnsLookup,
        });
        searchOutcome = resSearch.outcome;
        searchRequestsUsed = resSearch.requestsUsed;

        params.onSearchEvent?.({
          type: 'search_results',
          queries: searchOutcome.queries,
          sources: searchOutcome.sources,
          warning: searchOutcome.warning,
        });

        searchContextSection = formatRetrievedSourcesForPrompt({
          sources: searchOutcome.sources,
          queries: searchOutcome.queries,
          allowFollowUpSearch: searchRequestsUsed < MAX_SEARCH_REQUESTS_PER_INTERACTION,
          remainingSearchBudget: Math.max(
            0,
            MAX_SEARCH_REQUESTS_PER_INTERACTION - searchRequestsUsed,
          ),
        });
      } catch (err) {
        if (err instanceof WebSearchError && err.code === 'CANCELLED') {
          throw err;
        }
        if (params.signal.aborted) {
          throw err;
        }
        const errMsg =
          err instanceof WebSearchError
            ? err.message
            : sanitizeErrorMessage(err) || 'Web search failed.';
        searchOutcome = {
          status: 'failed',
          queries: [initialQuery],
          sources: [],
          error: errMsg,
          searchedAt: new Date().toISOString(),
          providerName: params.searchConfig?.name,
        };
        params.onSearchEvent?.({
          type: 'search_error',
          queries: [initialQuery],
          error: errMsg,
        });
        searchContextSection = formatSearchFailureForPrompt(errMsg);
      }
    }

    const invokeModel = async (extraPromptSection: string) => {
      const fullPrompt = extraPromptSection
        ? `${params.baseUserPrompt}\n\n${extraPromptSection}`
        : params.baseUserPrompt;
      const messages = [
        { role: 'system' as const, content: `${SYSTEM_GENERATOR_PROMPT}\nAlways respond strictly with valid JSON.` },
        { role: 'user' as const, content: fullPrompt },
      ];
      if (params.stream && params.onDelta) {
        return streamByokCompletion({
          config: params.config,
          messages,
          jsonMode: true,
          maxTokens: 12288,
          signal: params.signal,
          fetchImpl: aiFetchImpl,
          skipDnsLookup,
          onDelta: params.onDelta,
        });
      }
      return callByokCompletionRaw({
        config: params.config,
        messages,
        jsonMode: true,
        maxTokens: 12288,
        signal: params.signal,
        fetchImpl: aiFetchImpl,
        skipDnsLookup,
      });
    };

    const parseOrRepairJson = async (rawOutput: string): Promise<Record<string, unknown>> => {
      try {
        return extractJsonObject(rawOutput);
      } catch {
        // Automatic single-pass JSON repair for lightweight models that wrap or trail text
        const repaired = await callByokCompletionRaw({
          config: params.config,
          messages: [
            {
              role: 'system',
              content:
                'You are a strict JSON repair formatter. Extract and return ONLY valid JSON preserving every file path and code content faithfully without adding placeholders.',
            },
            {
              role: 'user',
              content: `Repair this model output into valid JSON strictly matching { "projectName"?, "description"?, "summary": string, "files": [{ "path": string, "language": string, "content": string }] }:\n\n${rawOutput.slice(0, 28000)}`,
            },
          ],
          jsonMode: true,
          maxTokens: 12288,
          signal: params.signal,
          fetchImpl: aiFetchImpl,
          skipDnsLookup,
        });
        return extractJsonObject(repaired);
      }
    };

    let rawText = await invokeModel(searchContextSection);
    let parsed = await parseOrRepairJson(rawText);

    // Provider-independent optional follow-up search step
    if (
      parsed.action === 'search_more' &&
      Array.isArray(parsed.queries) &&
      parsed.queries.length > 0 &&
      searchOutcome.status !== 'failed' &&
      searchRequestsUsed < MAX_SEARCH_REQUESTS_PER_INTERACTION
    ) {
      const followUpQueries = parsed.queries
        .map((q) => (typeof q === 'string' ? q.trim() : ''))
        .filter(Boolean)
        .slice(0, MAX_SEARCH_REQUESTS_PER_INTERACTION - searchRequestsUsed);

      if (followUpQueries.length > 0) {
        params.onSearchEvent?.({
          type: 'search_start',
          queries: followUpQueries,
          phase: 'Running follow-up web research...',
        });

        try {
          const followUpRes = await searchService.search({
            rawConfig: params.searchConfig,
            queries: followUpQueries,
            existingSources: searchOutcome.sources,
            maxRequestsInTurn: MAX_SEARCH_REQUESTS_PER_INTERACTION,
            usedRequestsSoFar: searchRequestsUsed,
            signal: params.signal,
            fetchImpl: searchFetchImpl,
            skipDnsLookup,
          });
          searchRequestsUsed = followUpRes.requestsUsed;
          searchOutcome = {
            ...followUpRes.outcome,
            queries: Array.from(
              new Set([...searchOutcome.queries, ...followUpRes.outcome.queries]),
            ),
          };
          params.onSearchEvent?.({
            type: 'search_results',
            queries: searchOutcome.queries,
            sources: searchOutcome.sources,
            warning: searchOutcome.warning,
          });
          searchContextSection = formatRetrievedSourcesForPrompt({
            sources: searchOutcome.sources,
            queries: searchOutcome.queries,
            allowFollowUpSearch: false,
            remainingSearchBudget: 0,
          });
        } catch (err) {
          if (err instanceof WebSearchError && err.code === 'CANCELLED') throw err;
          if (params.signal.aborted) throw err;
          const warnMsg =
            err instanceof WebSearchError
              ? err.message
              : sanitizeErrorMessage(err) || 'Follow-up search failed.';
          searchOutcome = {
            ...searchOutcome,
            warning: warnMsg,
          };
          searchContextSection = formatRetrievedSourcesForPrompt({
            sources: searchOutcome.sources,
            queries: searchOutcome.queries,
            allowFollowUpSearch: false,
            remainingSearchBudget: 0,
          });
        }

        rawText = await invokeModel(searchContextSection);
        parsed = await parseOrRepairJson(rawText);
      }
    }

    // Strictly validate citations in summary against actual retrieved sources
    const activeSources = searchOutcome.status === 'performed' ? searchOutcome.sources : [];
    if (typeof parsed.summary === 'string') {
      const citationCheck = validateAndExtractCitations(parsed.summary, activeSources);
      parsed.summary = citationCheck.cleanedText;
      searchOutcome = {
        ...searchOutcome,
        citedIds: citationCheck.citedIds,
      };
    }

    return { parsed, searchOutcome };
  }

  // Streaming website generation (SSE) with disconnect cancellation & timeouts
  app.post(
    '/api/ai/generate/stream',
    requireVerifiedAuth,
    aiRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.AI_PROMPT, 'Generation stream request'),
    async (req: AuthenticatedRequest, res) => {
      const { prompt, providerConfig, enableAppAi, searchConfig, searchMode } = req.body as {
        prompt: string;
        providerConfig?: AiProviderConfig;
        enableAppAi?: boolean;
        searchConfig?: WebSearchConfig;
        searchMode?: WebSearchMode;
      };
      const effectiveEnableAppAi = shouldEnableAppAi(
        prompt || '',
        'on_request',
        typeof enableAppAi === 'boolean' ? enableAppAi : undefined,
      );
      let validatedProviderCfg: AiProviderConfig | undefined;
      let validatedSearchCfg: WebSearchConfig | undefined;
      try {
        if (providerConfig) validatedProviderCfg = validateAiProviderConfig(providerConfig);
        if (searchConfig) validatedSearchCfg = validateWebSearchConfig(searchConfig);
      } catch (valErr) {
        sendSecurityErrorResponse(res, valErr, 400);
        return;
      }
      const config = normalizeProviderConfigToStudio(validatedProviderCfg || providerConfig);

      const abortController = new AbortController();
      res.on('close', () => {
        if (!res.writableEnded) {
          abortController.abort();
        }
      });

      res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
      res.setHeader('Cache-Control', 'no-cache, no-transform');
      res.setHeader('Connection', 'keep-alive');
      res.flushHeaders?.();

      const sendEvent = (event: Record<string, unknown>) => {
        if (!res.writableEnded) {
          res.write(`data: ${JSON.stringify(event)}\n\n`);
        }
      };

      try {
        if (!prompt || !prompt.trim()) {
          sendEvent({ type: 'error', error: 'Prompt is required.' });
          res.end();
          return;
        }

        const providerTitle = config.name?.trim() || 'BYOK Model';
        sendEvent({
          type: 'phase',
          phase: `Connecting to ${providerTitle} (${config.model})...`,
        });

        const userPrompt = buildGenerateUserPrompt(prompt, effectiveEnableAppAi, config);
        let seenPaths: string[] = [];
        let lastEmitAt = 0;

        const { parsed, searchOutcome } = await runGroundedModelCall({
          queryText: prompt,
          searchMode,
          searchConfig,
          config,
          baseUserPrompt: userPrompt,
          signal: abortController.signal,
          stream: true,
          onSearchEvent: (ev) => sendEvent(ev),
          onDelta: (accumulated) => {
            const currentPaths = detectStreamedPaths(accumulated);
            const now = Date.now();
            if (currentPaths.length > seenPaths.length) {
              if (seenPaths.length > 0) {
                const justFinished = seenPaths[seenPaths.length - 1];
                sendEvent({ type: 'file_done', path: justFinished });
              }
              const active = currentPaths[currentPaths.length - 1];
              seenPaths = currentPaths;
              sendEvent({
                type: 'file_start',
                path: active,
                completedFiles: seenPaths.slice(0, -1),
                chars: accumulated.length,
              });
              lastEmitAt = now;
            } else if (now - lastEmitAt > 250) {
              lastEmitAt = now;
              sendEvent({
                type: 'progress',
                activeFile: seenPaths[seenPaths.length - 1],
                completedFiles: seenPaths.slice(0, -1),
                chars: accumulated.length,
              });
            }
          },
        });

        sendEvent({
          type: 'phase',
          phase: 'Validating files & preparing preview...',
          completedFiles: seenPaths,
          chars: 0,
        });

        const finalized = await postProcessGeneratedProject({
          parsed,
          prompt,
          config,
          signal: abortController.signal,
          onPhase: (phase) =>
            sendEvent({
              type: 'phase',
              phase,
              completedFiles: seenPaths,
              chars: 0,
            }),
        });
        finalized.searchOutcome = searchOutcome;
        clearIncident(config.provider, config.model);

        const verification = finalized.verification as ProjectVerificationResult | undefined;
        const isVerified = isVerificationValidForFiles(
          verification,
          (finalized.files as ProjectFile[]) || [],
        );

        if (req.authUser?.uid) {
          notificationService
            .sendNotificationToUser(req.authUser.uid, {
              title: isVerified ? 'Build Verified ✨' : 'Build Completed with Errors ⚠️',
              body: isVerified
                ? `"${finalized.projectName || 'Website'}" built and verified cleanly!`
                : `"${finalized.projectName || 'Website'}" finished, but build verification failed: ${verification?.bundleError || 'Unknown error'}`,
              data: { url: '/' },
              tag: 'generation-complete',
            })
            .catch(() => {});
        }

        sendEvent({ type: 'complete', result: finalized });
        res.end();
      } catch (err) {
        if (
          abortController.signal.aborted ||
          (err instanceof WebSearchError && err.code === 'CANCELLED')
        ) {
          if (!res.writableEnded) {
            sendEvent({ type: 'error', error: 'Generation cancelled.' });
            res.end();
          }
          return;
        }
        const status = getHttpStatusFromError(err);
        const message = sanitizeErrorMessage(err) || 'Generation failed';
        const incident = classifyModelError({
          status,
          message,
          provider: config.provider,
          model: config.model,
        });
        recordIncident(incident);
        sendEvent({ type: 'error', error: incident.message, incident });
        if (!res.writableEnded) res.end();
      }
    },
  );

  // Non-streaming website generation endpoint
  app.post(
    '/api/ai/generate',
    requireVerifiedAuth,
    aiRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.AI_PROMPT, 'Generation request'),
    async (req: AuthenticatedRequest, res) => {
      const { prompt, providerConfig, enableAppAi, searchConfig, searchMode } = req.body as {
        prompt: string;
        providerConfig?: AiProviderConfig;
        enableAppAi?: boolean;
        searchConfig?: WebSearchConfig;
        searchMode?: WebSearchMode;
      };
      const effectiveEnableAppAi = shouldEnableAppAi(
        prompt || '',
        'on_request',
        typeof enableAppAi === 'boolean' ? enableAppAi : undefined,
      );
      let validatedProviderCfg: AiProviderConfig | undefined;
      let validatedSearchCfg: WebSearchConfig | undefined;
      try {
        if (providerConfig) validatedProviderCfg = validateAiProviderConfig(providerConfig);
        if (searchConfig) validatedSearchCfg = validateWebSearchConfig(searchConfig);
      } catch (valErr) {
        sendSecurityErrorResponse(res, valErr, 400);
        return;
      }
      const config = normalizeProviderConfigToStudio(validatedProviderCfg || providerConfig);
      const abortController = new AbortController();
      res.on('close', () => {
        if (!res.writableEnded) abortController.abort();
      });

      try {
        if (!prompt || !prompt.trim()) {
          res.status(400).json({ error: 'Prompt is required.' });
          return;
        }

        const userPrompt = buildGenerateUserPrompt(prompt, effectiveEnableAppAi, config);
        const { parsed, searchOutcome } = await runGroundedModelCall({
          queryText: prompt,
          searchMode,
          searchConfig,
          config,
          baseUserPrompt: userPrompt,
          signal: abortController.signal,
          stream: false,
        });

        const finalized = await postProcessGeneratedProject({
          parsed,
          prompt,
          config,
          signal: abortController.signal,
        });
        finalized.searchOutcome = searchOutcome;
        clearIncident(config.provider, config.model);

        const verification = finalized.verification as ProjectVerificationResult | undefined;
        const isVerified = isVerificationValidForFiles(
          verification,
          (finalized.files as ProjectFile[]) || [],
        );

        if (req.authUser?.uid) {
          notificationService
            .sendNotificationToUser(req.authUser.uid, {
              title: isVerified ? 'Build Verified ✨' : 'Build Completed with Errors ⚠️',
              body: isVerified
                ? `"${finalized.projectName || 'Website'}" built and verified cleanly!`
                : `"${finalized.projectName || 'Website'}" finished, but build verification failed: ${verification?.bundleError || 'Unknown error'}`,
              data: { url: '/' },
              tag: 'generation-complete',
            })
            .catch(() => {});
        }

        res.json(finalized);
      } catch (err) {
        const status = getHttpStatusFromError(err);
        const message = sanitizeErrorMessage(err) || 'Generation failed';
        const incident = classifyModelError({
          status,
          message,
          provider: config.provider,
          model: config.model,
        });
        recordIncident(incident);
        res.status(status).json({ error: incident.message, incident });
      }
    },
  );

  // Streaming website refinement (SSE)
  app.post(
    '/api/ai/refine/stream',
    requireVerifiedAuth,
    aiRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.AI_PROMPT, 'Refinement stream request'),
    async (req: AuthenticatedRequest, res) => {
      const {
        instruction,
        files,
        selectedElement,
        providerConfig,
        enableAppAi,
        searchConfig,
        searchMode,
      } = req.body as {
        instruction: string;
        files: ProjectFile[];
        selectedElement?: { tagName: string; textContent: string; className: string };
        providerConfig?: AiProviderConfig;
        enableAppAi?: boolean;
        searchConfig?: WebSearchConfig;
        searchMode?: WebSearchMode;
      };
      const effectiveEnableAppAi = shouldEnableAppAi(
        instruction || '',
        'on_request',
        typeof enableAppAi === 'boolean' ? enableAppAi : undefined,
      );
      let validatedProviderCfg: AiProviderConfig | undefined;
      let validatedSearchCfg: WebSearchConfig | undefined;
      try {
        if (providerConfig) validatedProviderCfg = validateAiProviderConfig(providerConfig);
        if (searchConfig) validatedSearchCfg = validateWebSearchConfig(searchConfig);
      } catch (valErr) {
        sendSecurityErrorResponse(res, valErr, 400);
        return;
      }
      const config = normalizeProviderConfigToStudio(validatedProviderCfg || providerConfig);

      const abortController = new AbortController();
      res.on('close', () => {
        if (!res.writableEnded) {
          abortController.abort();
        }
      });

      res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
      res.setHeader('Cache-Control', 'no-cache, no-transform');
      res.setHeader('Connection', 'keep-alive');
      res.flushHeaders?.();

      const sendEvent = (event: Record<string, unknown>) => {
        if (!res.writableEnded) {
          res.write(`data: ${JSON.stringify(event)}\n\n`);
        }
      };

      try {
        if (!instruction || !instruction.trim()) {
          sendEvent({ type: 'error', error: 'Refinement instruction is required.' });
          res.end();
          return;
        }
        const validatedInputFiles = validateProjectFilesPayload(files || []);

        const providerTitle = config.name?.trim() || 'BYOK Model';
        sendEvent({
          type: 'phase',
          phase: `Analyzing codebase with ${providerTitle} (${config.model})...`,
        });

        const userPrompt = buildRefineUserPrompt(
          instruction,
          validatedInputFiles,
          selectedElement,
          effectiveEnableAppAi,
          config,
        );
        let seenPaths: string[] = [];
        let lastEmitAt = 0;

        const { parsed, searchOutcome } = await runGroundedModelCall({
          queryText: instruction,
          searchMode,
          searchConfig,
          config,
          baseUserPrompt: userPrompt,
          signal: abortController.signal,
          stream: true,
          onSearchEvent: (ev) => sendEvent(ev),
          onDelta: (accumulated) => {
            const currentPaths = detectStreamedPaths(accumulated);
            const now = Date.now();
            if (currentPaths.length > seenPaths.length) {
              if (seenPaths.length > 0) {
                sendEvent({ type: 'file_done', path: seenPaths[seenPaths.length - 1] });
              }
              const active = currentPaths[currentPaths.length - 1];
              seenPaths = currentPaths;
              sendEvent({
                type: 'file_start',
                path: active,
                completedFiles: seenPaths.slice(0, -1),
                chars: accumulated.length,
              });
              lastEmitAt = now;
            } else if (now - lastEmitAt > 250) {
              lastEmitAt = now;
              sendEvent({
                type: 'progress',
                activeFile: seenPaths[seenPaths.length - 1],
                completedFiles: seenPaths.slice(0, -1),
                chars: accumulated.length,
              });
            }
          },
        });

        if (Array.isArray(parsed.files)) {
          const refinedVerified = await verifyRefinementResult({
            inputFiles: validatedInputFiles,
            refinedRawFiles: parsed.files as Array<{
              path: string;
              language?: ProjectFile['language'];
              content: string;
            }>,
            title: typeof parsed.projectName === 'string' ? parsed.projectName : 'Mist Preview',
            config,
            instruction,
            signal: abortController.signal,
            onPhase: (phase) =>
              sendEvent({
                type: 'phase',
                phase,
                completedFiles: seenPaths,
                chars: 0,
              }),
          });
          parsed.files = refinedVerified.files;
          parsed.verification = refinedVerified.verification;
          if (refinedVerified.repairAttempts > 0) {
            parsed.repairAttempts = refinedVerified.repairAttempts;
          }
        }
        parsed.searchOutcome = searchOutcome;

        clearIncident(config.provider, config.model);
        sendEvent({ type: 'complete', result: parsed });
        res.end();
      } catch (err) {
        if (
          abortController.signal.aborted ||
          (err instanceof WebSearchError && err.code === 'CANCELLED')
        ) {
          if (!res.writableEnded) {
            sendEvent({ type: 'error', error: 'Refinement cancelled.' });
            res.end();
          }
          return;
        }
        const status = getHttpStatusFromError(err);
        const message = sanitizeErrorMessage(err) || 'Refinement failed';
        const incident = classifyModelError({
          status,
          message,
          provider: config.provider,
          model: config.model,
        });
        recordIncident(incident);
        sendEvent({ type: 'error', error: incident.message, incident });
        if (!res.writableEnded) res.end();
      }
    },
  );

  // Standard non-streaming refine endpoint
  app.post(
    '/api/ai/refine',
    requireVerifiedAuth,
    aiRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.AI_PROMPT, 'Refinement request'),
    async (req: AuthenticatedRequest, res) => {
      const {
        instruction,
        files,
        selectedElement,
        providerConfig,
        enableAppAi,
        searchConfig,
        searchMode,
      } = req.body as {
        instruction: string;
        files: ProjectFile[];
        selectedElement?: { tagName: string; textContent: string; className: string };
        providerConfig?: AiProviderConfig;
        enableAppAi?: boolean;
        searchConfig?: WebSearchConfig;
        searchMode?: WebSearchMode;
      };
      const effectiveEnableAppAi = shouldEnableAppAi(
        instruction || '',
        'on_request',
        typeof enableAppAi === 'boolean' ? enableAppAi : undefined,
      );
      let validatedProviderCfg: AiProviderConfig | undefined;
      let validatedSearchCfg: WebSearchConfig | undefined;
      try {
        if (providerConfig) validatedProviderCfg = validateAiProviderConfig(providerConfig);
        if (searchConfig) validatedSearchCfg = validateWebSearchConfig(searchConfig);
      } catch (valErr) {
        sendSecurityErrorResponse(res, valErr, 400);
        return;
      }
      const config = normalizeProviderConfigToStudio(validatedProviderCfg || providerConfig);
      const abortController = new AbortController();
      res.on('close', () => {
        if (!res.writableEnded) abortController.abort();
      });

      try {
        if (!instruction || !instruction.trim()) {
          res.status(400).json({ error: 'Refinement instruction is required.' });
          return;
        }
        const validatedInputFiles = validateProjectFilesPayload(files || []);

        const userPrompt = buildRefineUserPrompt(
          instruction,
          validatedInputFiles,
          selectedElement,
          effectiveEnableAppAi,
          config,
        );

        const { parsed, searchOutcome } = await runGroundedModelCall({
          queryText: instruction,
          searchMode,
          searchConfig,
          config,
          baseUserPrompt: userPrompt,
          signal: abortController.signal,
          stream: false,
        });

        if (Array.isArray(parsed.files)) {
          const refinedVerified = await verifyRefinementResult({
            inputFiles: validatedInputFiles,
            refinedRawFiles: parsed.files as Array<{
              path: string;
              language?: ProjectFile['language'];
              content: string;
            }>,
            title: typeof parsed.projectName === 'string' ? parsed.projectName : 'Mist Preview',
            config,
            instruction,
            signal: abortController.signal,
          });
          parsed.files = refinedVerified.files;
          parsed.verification = refinedVerified.verification;
          if (refinedVerified.repairAttempts > 0) {
            parsed.repairAttempts = refinedVerified.repairAttempts;
          }
        }
        parsed.searchOutcome = searchOutcome;

        clearIncident(config.provider, config.model);
        res.json(parsed);
      } catch (err) {
        const status = getHttpStatusFromError(err);
        const message = sanitizeErrorMessage(err) || 'Refinement failed';
        const incident = classifyModelError({
          status,
          message,
          provider: config.provider,
          model: config.model,
        });
        recordIncident(incident);
        res.status(status).json({ error: incident.message, incident });
      }
    },
  );

  // Pure BYOK Voice Studio conversational turn
  app.post(
    '/api/ai/voice-turn',
    requireVerifiedAuth,
    aiRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.AI_PROMPT, 'Voice turn request'),
    async (req: AuthenticatedRequest, res) => {
      const { messages, mode, projectName, providerConfig } = req.body as {
        messages: Array<{ role: 'user' | 'assistant'; content: string }>;
        mode?: 'create' | 'refine';
        projectName?: string;
        providerConfig?: AiProviderConfig;
      };
      let validatedProviderCfg: AiProviderConfig | undefined;
      try {
        if (providerConfig) validatedProviderCfg = validateAiProviderConfig(providerConfig);
      } catch (valErr) {
        sendSecurityErrorResponse(res, valErr, 400);
        return;
      }
      const config = normalizeProviderConfigToStudio(validatedProviderCfg || providerConfig);

      try {
        const sys =
          mode === 'refine' && projectName
            ? `You are Mist, a sharp, concise AI website & game design partner speaking aloud with a user refining "${projectName}". Keep each response crisp (1-3 short conversational sentences), practical, and focused on concrete UI, color, physics, or feature decisions.`
            : 'You are Mist, a sharp, concise AI website & game design partner speaking aloud with a user brainstorming a new site or game. Keep each response crisp (1-3 short conversational sentences), helpful, and actionable.';

        const chatMessages: Array<{ role: 'system' | 'user' | 'assistant'; content: string }> = [
          { role: 'system', content: sys },
          ...(Array.isArray(messages) ? messages : []),
        ];

        const text = await callByokCompletionRaw({
          config,
          messages: chatMessages,
          jsonMode: false,
          temperature: 0.65,
          maxTokens: 512,
          fetchImpl: aiFetchImpl,
          skipDnsLookup,
        });

        clearIncident(config.provider, config.model);
        res.json({ text: text.trim(), provider: config.name || config.provider, model: config.model });
      } catch (err) {
        const status = getHttpStatusFromError(err);
        const message = sanitizeErrorMessage(err) || 'Voice request failed';
        const incident = classifyModelError({
          status,
          message,
          provider: config.provider,
          model: config.model,
        });
        recordIncident(incident);
        res.status(status).json({ error: incident.message, incident });
      }
    },
  );

  // Live BYOK AI runtime endpoint: accepts EITHER a valid ephemeral preview sessionToken OR verified Firebase Auth Bearer
  app.post(
    '/api/app-ai',
    aiRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.AI_PROMPT, 'App AI request'),
    async (req: AuthenticatedRequest, res) => {
      const { prompt, messages, systemInstruction, jsonMode, sessionToken, providerConfig } = req.body as {
        prompt?: string;
        messages?: Array<{ role: 'user' | 'assistant' | 'system'; content: string }>;
        systemInstruction?: string;
        jsonMode?: boolean;
        sessionToken?: string;
        providerConfig?: AiProviderConfig;
      };

      const headerToken =
        typeof req.headers['x-mist-session'] === 'string' ? req.headers['x-mist-session'] : undefined;
      const sessionResolved = resolvePreviewAiSession(sessionToken || headerToken);

      let authUser: VerifiedFirebaseUser | null = null;
      if (!sessionResolved) {
        try {
          authUser = await verifyAuth(req.headers.authorization);
          if (!authUser.emailVerified) {
            res.status(403).json({ error: 'A verified Google account is required to invoke App AI.' });
            return;
          }
          req.authUser = authUser;
        } catch (authErr) {
          sendSecurityErrorResponse(res, authErr, 401);
          return;
        }
      }

      let validatedProviderCfg: AiProviderConfig | undefined;
      try {
        if (!sessionResolved && providerConfig) {
          validatedProviderCfg = validateAiProviderConfig(providerConfig);
        }
      } catch (valErr) {
        sendSecurityErrorResponse(res, valErr, 400);
        return;
      }

      const config = sessionResolved
        ? normalizeProviderConfigToStudio(sessionResolved)
        : normalizeProviderConfigToStudio(validatedProviderCfg || providerConfig);

      const abortController = new AbortController();
      res.on('close', () => {
        if (!res.writableEnded) abortController.abort();
      });

      try {
        const trimmedPrompt = (prompt || '').trim();
        const hasMessages = Array.isArray(messages) && messages.length > 0;
        if (!trimmedPrompt && !hasMessages) {
          res.status(400).json({ error: 'Provide either prompt or messages.' });
          return;
        }

        const chatMessages: Array<{ role: 'system' | 'user' | 'assistant'; content: string }> = [
          {
            role: 'system',
            content:
              systemInstruction ||
              'You are a concise, helpful backend AI powering an interactive web application built with Mist.',
          },
          ...(hasMessages ? messages! : [{ role: 'user' as const, content: trimmedPrompt }]),
        ];

        const text = await callByokCompletionRaw({
          config,
          messages: chatMessages,
          jsonMode: Boolean(jsonMode),
          temperature: 0.6,
          maxTokens: 2048,
          timeoutMs: 45_000,
          signal: abortController.signal,
          fetchImpl: aiFetchImpl,
          skipDnsLookup,
        });

        clearIncident(config.provider, config.model);
        res.json({
          text,
          provider: config.name || config.provider,
          model: config.model,
        });
      } catch (err) {
        const status = getHttpStatusFromError(err);
        const message = sanitizeErrorMessage(err) || 'App AI runtime failed';
        const incident = classifyModelError({
          status,
          message,
          provider: config.provider,
          model: config.model,
        });
        recordIncident(incident);
        res.status(status).json({ error: incident.message, incident });
      }
    },
  );

  // --- 5. Durable Owner-Isolated Deployments API & Dedicated Publishing Host Routing ---
  app.get(
    '/api/deployments',
    requireVerifiedAuth,
    deployRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        const list = await deploymentStore.listByOwner(user.uid, user.idToken, publishBaseUrl);
        res.json({ deployments: list });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 500;
        res.status(status).json({ error: sanitizeErrorMessage(err) || 'Failed to load deployments' });
      }
    },
  );

  app.post(
    '/api/deployments',
    requireVerifiedAuth,
    deployRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.DEPLOYMENT, 'Deploy request'),
    async (req: AuthenticatedRequest, res) => {
      try {
        const authUser = req.authUser!;
        const { slug, projectId, title, files, enableAppAi } = req.body as {
          slug: string;
          projectId: string;
          title: string;
          files: ProjectFile[];
          enableAppAi?: boolean;
        };
        const cleanSlug = (slug || '')
          .toLowerCase()
          .replace(/[^a-z0-9-]+/g, '-')
          .replace(/^-+|-+$/g, '');
        if (cleanSlug.length < 2 || cleanSlug.length > 80) {
          res.status(400).json({ error: 'Deployment slug must be 2 to 80 URL-safe characters.' });
          return;
        }

        if (!publishBaseUrl) {
          res.status(400).json({
            error:
              'Public website publishing is disabled because PUBLISH_BASE_URL is not configured. Use project export (ZIP or standalone HTML) to host externally.',
          });
          return;
        }

        const publishedUrl = formatDeploymentUrl(cleanSlug, publishBaseUrl);
        if (!publishedUrl) {
          res.status(400).json({
            error: 'Invalid publishing domain configuration or slug.',
          });
          return;
        }

        const validatedFiles = validateProjectFilesPayload(files, { requireNonEmpty: true });
        const safeProjectId = (projectId || cleanSlug).replace(/[^a-zA-Z0-9_\-]/g, '-').slice(0, 128);
        const safeTitle = (title || cleanSlug).trim().slice(0, 120) || cleanSlug;

        const { html, bundleError } = await bundleProjectToHtml({
          files: validatedFiles,
          title: safeTitle,
          includeInspector: false,
          enableAppAi: Boolean(enableAppAi),
        });
        if (bundleError) {
          res.status(400).json({ error: `Cannot publish broken build: ${bundleError}` });
          return;
        }

        const saved = await deploymentStore.upsertOwned(
          {
            slug: cleanSlug,
            ownerUid: authUser.userId,
            projectId: safeProjectId,
            title: safeTitle,
            htmlBundle: html,
          },
          authUser.idToken,
        );

        // Fire-and-forget push notification to owner
        notificationService
          .sendNotificationToUser(authUser.userId, {
            title: 'Website Deployed! 🚀',
            body: `"${saved.title}" is now live at ${publishedUrl}`,
            data: { url: publishedUrl },
            tag: `deploy-${saved.slug}`,
          })
          .catch((err) => {
            console.warn('[Mist Notifications] Failed to dispatch deploy push notification:', err);
          });

        res.json({
          slug: saved.slug,
          url: publishedUrl,
          subdomainUrl: publishedUrl,
          publishedUrl,
          title: saved.title,
          updatedAt: saved.updatedAt,
          htmlBundle: saved.htmlBundle,
        });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 500;
        res.status(status).json({ error: sanitizeErrorMessage(err) || 'Deployment failed' });
      }
    },
  );

  app.delete(
    '/api/deployments/:slug',
    requireVerifiedAuth,
    deployRateLimiter,
    async (req: AuthenticatedRequest, res) => {
      try {
        const authUser = req.authUser!;
        const cleanSlug = (req.params.slug || '').toLowerCase().replace(/[^a-z0-9-]+/g, '-');
        if (!cleanSlug) {
          res.status(400).json({ error: 'Invalid deployment slug.' });
          return;
        }
        await deploymentStore.deleteOwned(cleanSlug, authUser.userId, authUser.idToken);
        res.json({ ok: true, slug: cleanSlug });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 500;
        res.status(status).json({ error: sanitizeErrorMessage(err) || 'Delete deployment failed' });
      }
    },
  );

  // --- 5.5. Batched Project Sync Dump on App Exit ---
  app.post(
    '/api/projects/sync-dump',
    requireVerifiedAuth,
    syncRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.PROJECT_SYNC, 'Sync dump request'),
    async (req: AuthenticatedRequest, res) => {
      try {
        const authUser = req.authUser!;
        const { projects } = req.body as { projects?: unknown[] };
        if (!Array.isArray(projects) || projects.length === 0) {
          res.json({
            ok: true,
            success: true,
            syncedProjects: 0,
            syncedFiles: 0,
            successfulProjectIds: [],
            failedProjects: [],
            user: authUser.email || authUser.userId,
            userEmail: authUser.email,
          });
          return;
        }

        // Limit maximum projects per batch
        if (projects.length > 50) {
          res.status(400).json({
            ok: false,
            success: false,
            error: 'Sync batch exceeds maximum allowed projects (50).',
          });
          return;
        }

        const successfulProjectIds: string[] = [];
        const failedProjects: Array<{ id: string; error: string }> = [];
        let totalFiles = 0;

        for (const rawProject of projects) {
          try {
            const validated = validateProjectPayload(rawProject);
            await adminStore.saveProject(authUser.userId, validated);
            successfulProjectIds.push(validated.id);
            totalFiles += validated.files.length;
          } catch (err) {
            const rawId = (rawProject as any)?.id;
            console.warn(`[Mist SyncDump] Failed to save project ${rawId}:`, err);
            failedProjects.push({
              id: typeof rawId === 'string' && rawId ? rawId : 'unknown',
              error: sanitizeErrorMessage(err) || 'Failed to save project',
            });
          }
        }

        const allSucceeded = failedProjects.length === 0;
        const anySucceeded = successfulProjectIds.length > 0;
        const statusCode = allSucceeded ? 200 : (anySucceeded ? 207 : 400);

        if (allSucceeded) {
          console.log(
            `[Mist SyncDump] App exit sync: dumped ${totalFiles} files across ${successfulProjectIds.length} projects for user ${authUser.email || authUser.userId} (${authUser.userId}) to Firebase`,
          );
        } else {
          console.warn(
            `[Mist SyncDump] App exit sync partial failure: ${successfulProjectIds.length} succeeded, ${failedProjects.length} failed for user ${authUser.email || authUser.userId}`,
          );
        }

        res.status(statusCode).json({
          ok: allSucceeded,
          success: allSucceeded,
          syncedProjects: successfulProjectIds.length,
          syncedFiles: totalFiles,
          successfulProjectIds,
          failedProjects,
          user: authUser.email || authUser.userId,
          userEmail: authUser.email,
        });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 500;
        res.status(status).json({
          ok: false,
          success: false,
          error: sanitizeErrorMessage(err) || 'Sync dump failed',
        });
      }
    },
  );


  // --- 6. Web Push Notifications (VAPID) ---
  app.get('/sw.js', (_req, res) => {
    const swPath = path.resolve(process.cwd(), 'public', 'sw.js');
    if (fs.existsSync(swPath)) {
      res.setHeader('Content-Type', 'application/javascript; charset=utf-8');
      res.setHeader('Service-Worker-Allowed', '/');
      res.setHeader('Cache-Control', 'no-cache');
      res.sendFile(swPath);
    } else {
      res.status(404).send('Service worker not found.');
    }
  });

  app.get('/api/notifications/vapid-public-key', (_req, res) => {
    res.json(notificationService.getVapidPublicConfig());
  });

  app.post(
    '/api/notifications/subscribe',
    requireVerifiedAuth,
    notificationRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.NOTIFICATIONS, 'Subscription request'),
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        const { subscription } = req.body as { subscription?: unknown };
        if (!subscription || typeof subscription !== 'object') {
          res.status(400).json({ error: 'Valid PushSubscription payload with keys is required.' });
          return;
        }
        const rawSub = subscription as Record<string, unknown>;
        const record = await notificationService.addSubscription(
          {
            endpoint: String(rawSub.endpoint || ''),
            expirationTime: typeof rawSub.expirationTime === 'number' ? rawSub.expirationTime : null,
            keys: rawSub.keys as any,
          },
          user.userId,
        );
        res.json({ ok: true, subscription: record });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 400;
        res.status(status).json({ error: sanitizeErrorMessage(err) || 'Failed to subscribe.' });
      }
    },
  );

  app.post(
    '/api/notifications/unsubscribe',
    requireVerifiedAuth,
    notificationRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.NOTIFICATIONS, 'Unsubscribe request'),
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        const { endpoint } = req.body as { endpoint?: string };
        if (!endpoint || typeof endpoint !== 'string') {
          res.status(400).json({ error: 'Endpoint is required.' });
          return;
        }
        const removed = await notificationService.removeSubscription(endpoint, user.userId);
        res.json({ ok: true, removed });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 400;
        res.status(status).json({ error: sanitizeErrorMessage(err) || 'Failed to unsubscribe.' });
      }
    },
  );

  app.post(
    '/api/notifications/test',
    requireVerifiedAuth,
    testNotificationRateLimiter,
    createBodySizeLimitMiddleware(BODY_LIMITS.NOTIFICATIONS, 'Test notification request'),
    async (req: AuthenticatedRequest, res) => {
      try {
        const user = req.authUser!;
        const { subscription } = req.body as { subscription?: unknown };

        const testPayload: NotificationPayload = {
          title: 'Mist Notification 🔔',
          body: 'Web Push with VAPID is working successfully on Mist!',
          icon: '/favicon.ico',
          badge: '/favicon.ico',
          data: { url: '/' },
          tag: 'test-notification',
        };

        // If client provides a subscription in request body:
        // Validate and associate with user.userId before sending (ownership & SSRF check!)
        if (subscription && typeof subscription === 'object') {
          const rawSub = subscription as Record<string, unknown>;
          if (rawSub.endpoint && rawSub.keys) {
            const verifiedSub = await notificationService.addSubscription(
              {
                endpoint: String(rawSub.endpoint || ''),
                expirationTime: typeof rawSub.expirationTime === 'number' ? rawSub.expirationTime : null,
                keys: rawSub.keys as any,
              },
              user.userId,
            );

            const result = await notificationService.sendNotification(verifiedSub, testPayload);
            if (!result.success) {
              res
                .status(result.statusCode || 500)
                .json({ error: result.error || 'Failed to deliver notification.' });
              return;
            }
            res.json({ ok: true });
            return;
          }
        }

        // Send to all verified subscriptions for this user account
        if (user?.userId) {
          const { sent, failed } = await notificationService.sendNotificationToUser(user.userId, testPayload);
          if (sent === 0 && failed === 0) {
            res.status(400).json({
              error: 'No active push subscriptions found for this account. Subscribe to push notifications first.',
            });
            return;
          }
          if (sent === 0 && failed > 0) {
            res.status(502).json({ error: 'Failed to deliver push notification to your registered devices.' });
            return;
          }
          res.json({ ok: true, sent, failed });
          return;
        }

        res.status(400).json({
          error: 'An active push subscription or verified sign-in is required to test notifications.',
        });
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 500;
        res.status(status).json({ error: sanitizeErrorMessage(err) || 'Test notification failed.' });
      }
    },
  );

  app.post(
    '/api/notifications/cleanup',
    requireVerifiedAuth,
    notificationRateLimiter,
    async (_req: AuthenticatedRequest, res) => {
      try {
        const cleaned = await notificationService.cleanupExpiredSubscriptions();
        res.json({ ok: true, cleaned });
      } catch (err) {
        res.status(500).json({ error: sanitizeErrorMessage(err) || 'Cleanup failed.' });
      }
    },
  );

  app.post(
    '/api/notifications/keys/generate',
    requireVerifiedAuth,
    notificationRateLimiter,
    (_req: AuthenticatedRequest, res) => {
      if (process.env.NODE_ENV === 'production') {
        res.status(403).json({ error: 'Key generation endpoint is disabled in production.' });
        return;
      }
      const keys = notificationService.generateNewKeypair();
      res.json(keys);
    },
  );

  const RESERVED_ROOT_SEGMENTS = new Set([
    'api',
    'p',
    'vendor',
    'src',
    'assets',
    'node_modules',
    'sw.js',
    'robots.txt',
    'sitemap.xml',
    'favicon.ico',
    'manifest.webmanifest',
  ]);

  // Dedicated publishing host root handler for wildcard subdomains (e.g. https://<slug>.mist-published.com/)
  app.get('/', async (req, res, next) => {
    const reqHost = getEffectiveHost(req);
    const { isPublishing, slug } = isPublishingHostname(reqHost, publishBaseUrl);
    if (!isPublishing || !slug) {
      // Normal builder root request -> pass through to SPA handler
      next();
      return;
    }

    try {
      const record = await deploymentStore.getPublic(slug);
      if (!record) {
        res
          .status(404)
          .setHeader('Content-Type', 'text/html; charset=utf-8')
          .send(
            `<!doctype html><html><body style="font-family:system-ui,sans-serif;padding:48px;max-width:560px;margin:0 auto;background:#09090b;color:#f4f4f5;"><h1>Site not found</h1><p style="color:#a1a1aa;">No Mist deployment exists for <code>${encodeURIComponent(slug)}</code>.</p></body></html>`,
          );
        return;
      }
      sendPublishedSiteHtml(res, record.htmlBundle);
    } catch (err) {
      const status = err instanceof SecurityValidationError ? err.status : 500;
      res.status(status).setHeader('Content-Type', 'text/plain; charset=utf-8').send(
        sanitizeErrorMessage(err) || 'Unable to load deployment.',
      );
    }
  });

  app.get('/p/:slug', async (req, res) => {
    const cleanSlug = (req.params.slug || '')
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, '-')
      .replace(/^-+|-+$/g, '');
    if (cleanSlug.length < 2) {
      res.status(404).setHeader('Content-Type', 'text/html; charset=utf-8').send('Site not found.');
      return;
    }

    const reqHost = getEffectiveHost(req);
    const { isPublishing } = isPublishingHostname(reqHost, publishBaseUrl);

    if (isPublishing) {
      // Served on dedicated publishing hostname:
      try {
        const record = await deploymentStore.getPublic(cleanSlug);
        if (!record) {
          res
            .status(404)
            .setHeader('Content-Type', 'text/html; charset=utf-8')
            .send(
              `<!doctype html><html><body style="font-family:system-ui,sans-serif;padding:48px;max-width:560px;margin:0 auto;background:#09090b;color:#f4f4f5;"><h1>Site not found</h1><p style="color:#a1a1aa;">No Mist deployment exists at <code>/p/${encodeURIComponent(cleanSlug)}</code>.</p></body></html>`,
            );
          return;
        }
        sendPublishedSiteHtml(res, record.htmlBundle);
      } catch (err) {
        const status = err instanceof SecurityValidationError ? err.status : 500;
        res.status(status).setHeader('Content-Type', 'text/plain; charset=utf-8').send(
          sanitizeErrorMessage(err) || 'Unable to load deployment.',
        );
      }
      return;
    }

    // On builder hostname:
    // NEVER execute arbitrary published HTML on the main Mist application origin!
    if (publishBaseUrl) {
      const targetUrl = formatDeploymentUrl(cleanSlug, publishBaseUrl);
      if (targetUrl) {
        res.redirect(301, targetUrl);
        return;
      }
    }

    res
      .status(404)
      .setHeader('Content-Type', 'text/html; charset=utf-8')
      .send(
        `<!doctype html><html><body style="font-family:system-ui,sans-serif;padding:48px;max-width:560px;margin:0 auto;background:#09090b;color:#f4f4f5;"><h1>Public publishing is disabled</h1><p style="color:#a1a1aa;">Public site hosting is disabled on this origin. Configure <code>PUBLISH_BASE_URL</code> or export the project to host externally.</p></body></html>`,
      );
  });

  // Short vanity route /:slug:
  // On dedicated publishing host: serve the published site HTML
  // On builder hostname: MUST NEVER execute arbitrary published HTML! Falls through to SPA router.
  app.get('/:slug', async (req, res, next) => {
    const reqHost = getEffectiveHost(req);
    const { isPublishing } = isPublishingHostname(reqHost, publishBaseUrl);

    // If on builder hostname, NEVER execute published HTML! Fall through to SPA.
    if (!isPublishing) {
      next();
      return;
    }

    const rawSlug = String(req.params.slug || '');
    const lowerSlug = rawSlug.toLowerCase();
    if (
      !lowerSlug ||
      rawSlug.includes('.') ||
      rawSlug.startsWith('@') ||
      rawSlug.startsWith('__') ||
      RESERVED_ROOT_SEGMENTS.has(lowerSlug) ||
      !/^[a-z0-9][a-z0-9-]{1,79}$/.test(lowerSlug)
    ) {
      next();
      return;
    }

    try {
      const record = await deploymentStore.getPublic(lowerSlug);
      if (!record) {
        res
          .status(404)
          .setHeader('Content-Type', 'text/html; charset=utf-8')
          .send(
            `<!doctype html><html><body style="font-family:system-ui,sans-serif;padding:48px;max-width:560px;margin:0 auto;background:#09090b;color:#f4f4f5;"><h1>Site not found</h1><p style="color:#a1a1aa;">No Mist deployment exists for <code>${encodeURIComponent(lowerSlug)}</code>.</p></body></html>`,
          );
        return;
      }
      sendPublishedSiteHtml(res, record.htmlBundle);
    } catch {
      next();
    }
  });

  // Centralized Error Handling Middleware: guarantees consistent JSON error response schema
  // and prevents Express from leaking unformatted HTML or stack traces.
  app.use((err: unknown, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
    sendSecurityErrorResponse(res, err, 500);
  });

  return app;
}
