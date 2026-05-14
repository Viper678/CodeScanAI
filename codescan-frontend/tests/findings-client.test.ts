import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchFindings, getExportUrl } from '@/lib/api/findings/client';

const originalFetch = globalThis.fetch;

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
    status: 200,
    ...init,
  });
}

beforeEach(() => {
  globalThis.fetch = vi.fn();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe('fetchFindings', () => {
  it('serializes severity + scan_type as comma-joined params and includes the cursor', async () => {
    const response = jsonResponse({
      items: [],
      next_cursor: null,
      total: 0,
    });
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(response);

    await fetchFindings('scan-1', {
      cursor: 'opaque-cursor',
      file_id: 'file-9',
      limit: 25,
      scan_type: ['security', 'bugs'],
      severity: ['high', 'critical'],
    });

    // Post-M7 ``apiFetch`` issues same-origin relative URLs (the web
    // container's Next.js ``rewrites()`` proxies ``/api/v1/*`` to the api
    // service server-side). Resolve against a synthetic base so ``new URL``
    // parses successfully — the path / query are what we actually assert on.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const firstCall = fetchMock.mock.calls[0]!;
    const url = firstCall[0] as string;
    expect(url.startsWith('/api/v1/')).toBe(true);
    const search = new URL(url, 'http://test.local').searchParams;
    expect(search.get('severity')).toBe('high,critical');
    expect(search.get('scan_type')).toBe('security,bugs');
    expect(search.get('file_id')).toBe('file-9');
    expect(search.get('cursor')).toBe('opaque-cursor');
    expect(search.get('limit')).toBe('25');
  });

  it('drops empty filter buckets and clamps limit to 1..200', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], next_cursor: null, total: 0 }),
    );

    await fetchFindings('scan-1', {
      file_id: null,
      // 250 should clamp to 200 (the actual server max from T4.1), not blow
      // up the API. The earlier 100 cap silently truncated the per-file
      // sidebar to half its intended window — see codex P1 on T4.3.
      limit: 250,
      scan_type: [],
      severity: [],
    });

    const call = fetchMock.mock.calls[0]!;
    const url = call[0] as string;
    expect(url.startsWith('/api/v1/')).toBe(true);
    const search = new URL(url, 'http://test.local').searchParams;
    expect(search.has('severity')).toBe(false);
    expect(search.has('scan_type')).toBe(false);
    expect(search.has('file_id')).toBe(false);
    expect(search.has('cursor')).toBe(false);
    expect(search.get('limit')).toBe('200');
  });
});

describe('getExportUrl', () => {
  // Post-M7 the export URL is same-origin / relative — the browser resolves
  // it against the document origin and Next.js ``rewrites()`` proxies it to
  // the api server-side. Resolve against a synthetic base just to parse the
  // path + query in tests; the actual return value is intentionally relative
  // (no scheme / host) so a single web image works across all envs.
  const TEST_ORIGIN = 'http://test.local';

  it('builds a same-origin path with fmt + active filters', () => {
    const url = getExportUrl('scan-1', 'csv', {
      file_id: null,
      scan_type: ['security'],
      severity: ['critical'],
    });
    expect(url.startsWith('/api/v1/')).toBe(true);
    const parsed = new URL(url, TEST_ORIGIN);
    expect(parsed.pathname).toBe('/api/v1/scans/scan-1/export');
    expect(parsed.searchParams.get('fmt')).toBe('csv');
    expect(parsed.searchParams.get('severity')).toBe('critical');
    expect(parsed.searchParams.get('scan_type')).toBe('security');
  });

  it('includes only fmt when no filters are active', () => {
    const url = getExportUrl('scan-2', 'json', {
      file_id: null,
      scan_type: [],
      severity: [],
    });
    expect(url.startsWith('/api/v1/')).toBe(true);
    const parsed = new URL(url, TEST_ORIGIN);
    expect([...parsed.searchParams.keys()]).toEqual(['fmt']);
    expect(parsed.searchParams.get('fmt')).toBe('json');
  });
});
