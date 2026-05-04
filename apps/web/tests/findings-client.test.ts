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

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const firstCall = fetchMock.mock.calls[0]!;
    const url = firstCall[0] as string;
    const search = new URL(url).searchParams;
    expect(search.get('severity')).toBe('high,critical');
    expect(search.get('scan_type')).toBe('security,bugs');
    expect(search.get('file_id')).toBe('file-9');
    expect(search.get('cursor')).toBe('opaque-cursor');
    expect(search.get('limit')).toBe('25');
  });

  it('drops empty filter buckets and clamps limit to 1..100', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], next_cursor: null, total: 0 }),
    );

    await fetchFindings('scan-1', {
      file_id: null,
      // 250 should clamp to 100, not blow up the API.
      limit: 250,
      scan_type: [],
      severity: [],
    });

    const call = fetchMock.mock.calls[0]!;
    const search = new URL(call[0] as string).searchParams;
    expect(search.has('severity')).toBe(false);
    expect(search.has('scan_type')).toBe(false);
    expect(search.has('file_id')).toBe(false);
    expect(search.has('cursor')).toBe(false);
    expect(search.get('limit')).toBe('100');
  });
});

describe('getExportUrl', () => {
  it('builds an absolute URL with fmt + active filters', () => {
    const url = getExportUrl('scan-1', 'csv', {
      file_id: null,
      scan_type: ['security'],
      severity: ['critical'],
    });
    const parsed = new URL(url);
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
    const parsed = new URL(url);
    expect([...parsed.searchParams.keys()]).toEqual(['fmt']);
    expect(parsed.searchParams.get('fmt')).toBe('json');
  });
});
