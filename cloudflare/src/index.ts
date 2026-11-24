/**
 * Cloudflare Worker for Mist
 *
 * Responsibilities:
 * 1. Static asset delivery for Mist main application (mist.me) via Workers Static Assets.
 * 2. Caching optimization (immutable caching for /assets/*, SPA fallback).
 * 3. Secure reverse proxying for /api/* to the private Heroku control plane.
 * 4. Injection of edge origin secret (MIST_EDGE_ORIGIN_SECRET) and client IP forwarding.
 * 5. SSE streaming pass-through without edge buffering.
 * 6. Wildcard subdomain routing for published projects (<slug>.mist.me).
 * 7. R2 artifact retrieval for published sites (sites/<slug>/index.html).
 * 8. Rejection of reserved and invalid subdomains.
 * 9. SPA fallback and branded 404 pages for published sites.
 */

export interface Env {
  ASSETS?: {
    fetch: (request: Request) => Promise<Response>;
  };
  PUBLISHED_BUCKET?: {
    get: (key: string) => Promise<{
      body: ReadableStream;
      httpMetadata?: { contentType?: string };
      httpEtag?: string;
    } | null>;
  };
  APEX_DOMAIN?: string;
  PUBLISH_DOMAIN?: string;
  HEROKU_API_ORIGIN?: string;
  MIST_EDGE_ORIGIN_SECRET?: string;
}

export const RESERVED_SUBDOMAINS = new Set([
  'www',
  'api',
  'auth',
  'admin',
  'dashboard',
  'assets',
  'status',
  'mail',
]);

const SLUG_REGEX = /^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$/;

/**
 * Validates a subdomain slug format.
 */
export function isValidSlug(slug: string): boolean {
  if (!slug || slug.length < 3 || slug.length > 63) return false;
  if (slug.includes('--')) return false; // reject consecutive hyphens
  return SLUG_REGEX.test(slug);
}

/**
 * Extracts and classifies the subdomain from the hostname given an apex domain
 * and optional dedicated wildcard publishing domain.
 */
export function extractSubdomain(
  hostname: string,
  apexDomain = 'mist.me',
  publishDomain?: string,
): { isApex: boolean; isPublishDomainApex?: boolean; subdomain: string | null } {
  const host = (hostname || '').toLowerCase().split(':')[0]!;
  const apex = (apexDomain || 'mist.me').toLowerCase().split(':')[0]!;
  const publish = publishDomain ? publishDomain.replace(/^\*\./, '').toLowerCase().split(':')[0]! : null;

  // 1. If a dedicated publishing domain is configured (e.g. sites.mist.me or mist-sites.com)
  if (publish && publish !== apex) {
    if (host === publish) {
      return { isApex: false, isPublishDomainApex: true, subdomain: null };
    }
    if (host.endsWith(`.${publish}`)) {
      const sub = host.slice(0, -(publish.length + 1));
      return { isApex: false, subdomain: sub };
    }
  }

  // 2. Apex / local development checks
  if (host === apex || host === 'localhost' || host === '127.0.0.1') {
    return { isApex: true, subdomain: null };
  }

  // 3. Subdomain of apex domain (e.g. my-app.mist.me)
  if (host.endsWith(`.${apex}`)) {
    const sub = host.slice(0, -(apex.length + 1));
    return { isApex: false, subdomain: sub };
  }

  // 4. Local testing subdomains (e.g. test.localhost)
  if (host.endsWith('.localhost')) {
    const sub = host.slice(0, -('.localhost'.length));
    return { isApex: false, subdomain: sub };
  }

  return { isApex: true, subdomain: null };
}

/**
 * Determines content type for static files stored in R2.
 */
export function getContentType(filePath: string): string {
  const ext = filePath.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'html':
    case 'htm':
      return 'text/html; charset=utf-8';
    case 'css':
      return 'text/css; charset=utf-8';
    case 'js':
    case 'mjs':
      return 'application/javascript; charset=utf-8';
    case 'json':
      return 'application/json; charset=utf-8';
    case 'svg':
      return 'image/svg+xml';
    case 'png':
      return 'image/png';
    case 'jpg':
    case 'jpeg':
      return 'image/jpeg';
    case 'gif':
      return 'image/gif';
    case 'webp':
      return 'image/webp';
    case 'ico':
      return 'image/x-icon';
    case 'txt':
      return 'text/plain; charset=utf-8';
    case 'woff2':
      return 'font/woff2';
    default:
      return 'application/octet-stream';
  }
}

/**
 * Generates a branded Mist 404 response for unpublished or missing project sites.
 */
export function render404Page(slug: string, apexDomain: string): Response {
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>404 - Site Not Found | Mist</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #09090b;
      color: #f4f4f5;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }
    .card {
      max-width: 480px;
      width: 100%;
      text-align: center;
      background: #18181b;
      border: 1px solid #27272a;
      border-radius: 16px;
      padding: 40px 32px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }
    .badge {
      display: inline-block;
      background: #27272a;
      color: #a1a1aa;
      padding: 6px 14px;
      border-radius: 9999px;
      font-size: 13px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      margin-bottom: 24px;
      border: 1px solid #3f3f46;
    }
    h1 {
      font-size: 26px;
      font-weight: 700;
      letter-spacing: -0.02em;
      margin-bottom: 12px;
      color: #ffffff;
    }
    p {
      font-size: 15px;
      line-height: 1.6;
      color: #a1a1aa;
      margin-bottom: 28px;
    }
    .btn {
      display: inline-block;
      background: #2563eb;
      color: #ffffff;
      font-weight: 600;
      font-size: 14px;
      text-decoration: none;
      padding: 12px 24px;
      border-radius: 8px;
      transition: background 0.15s ease;
    }
    .btn:hover {
      background: #1d4ed8;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">404 NOT FOUND</div>
    <h1>Project Unavailable</h1>
    <p>The published project at <strong>${encodeURIComponent(slug)}.${encodeURIComponent(apexDomain)}</strong> could not be found. It may have been unpublished, renamed, or not yet deployed.</p>
    <a class="btn" href="https://${encodeURIComponent(apexDomain)}">Create on Mist</a>
  </div>
</body>
</html>`;

  return new Response(html, {
    status: 404,
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      'X-Content-Type-Options': 'nosniff',
    },
  });
}

/**
 * Proxies API requests to the private Heroku control plane.
 */
export async function proxyToHeroku(
  request: Request,
  url: URL,
  env: Env,
): Promise<Response> {
  const herokuOrigin = (env.HEROKU_API_ORIGIN || 'https://mist-control-plane-api.herokuapp.com').replace(/\/+$/, '');
  const targetUrl = `${herokuOrigin}${url.pathname}${url.search}`;

  const forwardHeaders = new Headers(request.headers);

  // Security: Strip any client-supplied edge origin secret
  forwardHeaders.delete('x-mist-edge-secret');

  // Attach verified edge-origin secret if configured
  if (env.MIST_EDGE_ORIGIN_SECRET) {
    forwardHeaders.set('x-mist-edge-secret', env.MIST_EDGE_ORIGIN_SECRET);
  }

  // Pass along real client IP and host
  const clientIp = request.headers.get('cf-connecting-ip') || request.headers.get('x-forwarded-for') || '';
  if (clientIp) {
    forwardHeaders.set('x-forwarded-for', clientIp);
    forwardHeaders.set('cf-connecting-ip', clientIp);
  }

  forwardHeaders.set('x-forwarded-host', url.host || 'mist.me');
  forwardHeaders.set('x-forwarded-proto', 'https');

  // Override Host header to target Heroku domain
  try {
    const targetHost = new URL(herokuOrigin).host;
    forwardHeaders.set('host', targetHost);
  } catch {
    // fallback
  }

  // Hop-by-hop headers to strip
  forwardHeaders.delete('connection');
  forwardHeaders.delete('keep-alive');
  forwardHeaders.delete('transfer-encoding');
  forwardHeaders.delete('upgrade');

  const method = request.method.toUpperCase();
  const hasBody = method !== 'GET' && method !== 'HEAD';

  const fetchInit: RequestInit = {
    method,
    headers: forwardHeaders,
    body: hasBody ? request.body : undefined,
    redirect: 'follow',
  };

  // Node/Workers fetch compatibility for streaming requests
  if (hasBody && request.body) {
    (fetchInit as any).duplex = 'half';
  }

  try {
    const backendResponse = await fetch(targetUrl, fetchInit);

    // Stream response directly to client (unbuffered SSE & chunked transfer)
    const responseHeaders = new Headers(backendResponse.headers);

    // Preserve SSE and dynamic streaming
    const contentType = responseHeaders.get('content-type') || '';
    if (contentType.includes('text/event-stream')) {
      responseHeaders.set('Cache-Control', 'no-cache, no-transform');
      responseHeaders.set('X-Accel-Buffering', 'no');
    }

    return new Response(backendResponse.body, {
      status: backendResponse.status,
      statusText: backendResponse.statusText,
      headers: responseHeaders,
    });
  } catch (err: any) {
    return new Response(
      JSON.stringify({
        error: 'Edge proxy unable to reach Mist control plane.',
        details: err?.message || 'Unknown network error',
      }),
      {
        status: 502,
        headers: { 'Content-Type': 'application/json' },
      },
    );
  }
}

/**
 * Delivers published projects directly from Cloudflare R2 bucket.
 */
export async function handlePublishedSite(
  subdomain: string,
  request: Request,
  url: URL,
  env: Env,
): Promise<Response> {
  const apexDomain = env.APEX_DOMAIN || 'mist.me';

  // 1. Check reserved subdomains
  if (subdomain === 'www') {
    // Redirect www.mist.me to apex https://mist.me
    return Response.redirect(`https://${apexDomain}${url.pathname}${url.search}`, 301);
  }

  if (subdomain === 'api') {
    // Directly proxy api.mist.me to Heroku backend
    return proxyToHeroku(request, url, env);
  }

  if (RESERVED_SUBDOMAINS.has(subdomain)) {
    return new Response(
      `Forbidden: '${subdomain}' is a reserved subdomain on Mist.`,
      { status: 403, headers: { 'Content-Type': 'text/plain; charset=utf-8' } },
    );
  }

  // 2. Validate slug format
  if (!isValidSlug(subdomain)) {
    return new Response(
      `Bad Request: '${subdomain}' is not a valid subdomain. Subdomains must be 3-63 lowercase alphanumeric characters and hyphens.`,
      { status: 400, headers: { 'Content-Type': 'text/plain; charset=utf-8' } },
    );
  }

  // 3. Reject non-GET / non-HEAD requests for published static sites
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response('Method Not Allowed', { status: 405 });
  }

  if (!env.PUBLISHED_BUCKET) {
    return new Response('Configuration Error: R2 PUBLISHED_BUCKET binding is missing.', { status: 500 });
  }

  // 4. Resolve R2 key
  const cleanPath = url.pathname.replace(/^\/+/, '');
  const isDirectFile = cleanPath.length > 0 && cleanPath !== 'index.html';

  let r2Key = isDirectFile ? `sites/${subdomain}/${cleanPath}` : `sites/${subdomain}/index.html`;

  let object = await env.PUBLISHED_BUCKET.get(r2Key);

  // 5. SPA Fallback: If direct file not found, fall back to sites/<slug>/index.html
  if (!object && isDirectFile) {
    r2Key = `sites/${subdomain}/index.html`;
    object = await env.PUBLISHED_BUCKET.get(r2Key);
  }

  // 6. If not found in R2, return branded 404
  if (!object) {
    return render404Page(subdomain, apexDomain);
  }

  // 7. Return artifact with appropriate caching and security headers
  const contentType = object.httpMetadata?.contentType || getContentType(r2Key);

  const headers = new Headers();
  headers.set('Content-Type', contentType);
  headers.set('Cache-Control', 'public, max-age=60, s-maxage=300, stale-while-revalidate=86400');
  headers.set('X-Content-Type-Options', 'nosniff');
  headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  headers.set('X-Frame-Options', 'DENY');
  headers.set('Cross-Origin-Opener-Policy', 'same-origin');
  headers.set(
    'Content-Security-Policy',
    "sandbox allow-scripts allow-forms allow-popups; default-src 'unsafe-inline' 'unsafe-eval' data: blob: https:; img-src * data: blob: https:; media-src * data: blob: https:; style-src * 'unsafe-inline'; font-src * data: https:; connect-src *; object-src 'none'; base-uri 'none'; frame-ancestors 'none';",
  );
  headers.delete('Set-Cookie');
  if (object.httpEtag) {
    headers.set('ETag', object.httpEtag);
  }

  return new Response(request.method === 'HEAD' ? null : object.body, {
    status: 200,
    headers,
  });
}

/**
 * Main Cloudflare Worker fetch handler.
 */
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const apexDomain = env.APEX_DOMAIN || 'mist.me';
    const publishDomain = env.PUBLISH_DOMAIN;

    // 1. Edge health check
    if (url.pathname === '/cdn-health' || url.pathname === '/__edge/health') {
      return new Response(
        JSON.stringify({
          status: 'healthy',
          edge: 'cloudflare-worker',
          apexDomain,
          publishDomain: publishDomain || apexDomain,
          timestamp: new Date().toISOString(),
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      );
    }

    // 2. Classify domain (apex vs subdomain vs publish domain apex)
    const { isApex, isPublishDomainApex, subdomain } = extractSubdomain(url.hostname, apexDomain, publishDomain);

    // If request reached the apex of the publishing domain (e.g. sites.mist.me or mist-sites.com without slug)
    if (isPublishDomainApex) {
      return Response.redirect(`https://${apexDomain}/`, 302);
    }

    // 3. Subdomain branch: Published projects (<slug>.mist.me or <slug>.<publishDomain>)
    if (!isApex && subdomain) {
      return handlePublishedSite(subdomain, request, url, env);
    }

    // 4. Apex domain branch: mist.me
    // Disallow arbitrary published site HTML on apex and redirect legacy /p/:slug to subdomain
    if (url.pathname.startsWith('/p/')) {
      const slug = url.pathname.slice(3).split('/')[0];
      if (slug && isValidSlug(slug)) {
        const targetDomain = publishDomain ? publishDomain.replace(/^\*\./, '') : apexDomain;
        return Response.redirect(`https://${slug}.${targetDomain}/`, 301);
      }
      return new Response('Not Found: Published website routes are disabled on apex origin.', { status: 404 });
    }

    // Route /api/* and /sw.js to Heroku API
    if (url.pathname.startsWith('/api/') || url.pathname === '/sw.js') {
      return proxyToHeroku(request, url, env);
    }

    // Static Assets delivery via Workers Static Assets (env.ASSETS)
    if (!env.ASSETS) {
      return new Response('Edge error: ASSETS binding unavailable.', { status: 500 });
    }

    const assetResponse = await env.ASSETS.fetch(request);

    // Add immutable caching headers for versioned build assets (/assets/*)
    if (url.pathname.startsWith('/assets/')) {
      const responseHeaders = new Headers(assetResponse.headers);
      responseHeaders.set('Cache-Control', 'public, max-age=31536000, immutable');
      return new Response(assetResponse.body, {
        status: assetResponse.status,
        statusText: assetResponse.statusText,
        headers: responseHeaders,
      });
    }

    return assetResponse;
  },
};
