import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  deleteScan,
  fetchScans,
  pauseScan,
  rerunScan,
  resumeScan,
} from '@/lib/api/scans/client';

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

describe('fetchScans', () => {
  it('serializes status as a comma-joined list and forwards upload_id', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], next_cursor: null, total: 0 }),
    );

    await fetchScans({
      limit: 10,
      offset: 0,
      status: ['running', 'completed'],
      upload_id: 'upload-9',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = fetchMock.mock.calls[0]![0] as string;
    const search = new URL(url).searchParams;
    expect(search.get('status')).toBe('running,completed');
    expect(search.get('upload_id')).toBe('upload-9');
    expect(search.get('limit')).toBe('10');
    expect(search.get('offset')).toBe('0');
  });

  it('drops empty status and missing upload_id from the query string', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], next_cursor: null, total: 0 }),
    );

    await fetchScans({ status: [] });

    const url = fetchMock.mock.calls[0]![0] as string;
    const search = new URL(url).searchParams;
    expect(search.has('status')).toBe(false);
    expect(search.has('upload_id')).toBe(false);
    // Limit / offset still present with their defaults so the server doesn't
    // have to think about edges.
    expect(search.get('limit')).toBe('20');
    expect(search.get('offset')).toBe('0');
  });

  it('clamps limit to 1..100', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], next_cursor: null, total: 0 }),
    );

    await fetchScans({ limit: 9_999 });

    const url = fetchMock.mock.calls[0]![0] as string;
    expect(new URL(url).searchParams.get('limit')).toBe('100');
  });
});

describe('rerunScan', () => {
  it('POSTs to /scans/{id}/rerun with the CSRF header and returns the new scan id', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          id: 'new-scan',
          progress_done: 0,
          progress_total: 5,
          status: 'pending',
        },
        { status: 202 },
      ),
    );

    const result = await rerunScan('source-scan');

    expect(result.id).toBe('new-scan');
    const call = fetchMock.mock.calls[0]!;
    const url = call[0] as string;
    const init = call[1] as RequestInit;
    expect(url.endsWith('/scans/source-scan/rerun')).toBe(true);
    expect(init.method).toBe('POST');
    const headers = init.headers as Headers;
    expect(headers.get('X-Requested-With')).toBe('codescan');
  });
});

describe('pauseScan', () => {
  it('POSTs to /scans/{id}/pause with the CSRF header', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: 'scan-1',
        progress_done: 47,
        progress_total: 312,
        status: 'paused',
      }),
    );

    const result = await pauseScan('scan-1');

    expect(result.status).toBe('paused');
    const call = fetchMock.mock.calls[0]!;
    expect((call[0] as string).endsWith('/scans/scan-1/pause')).toBe(true);
    const init = call[1] as RequestInit;
    expect(init.method).toBe('POST');
    expect((init.headers as Headers).get('X-Requested-With')).toBe('codescan');
  });
});

describe('resumeScan', () => {
  it('POSTs to /scans/{id}/resume with the CSRF header', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          id: 'scan-1',
          progress_done: 47,
          progress_total: 312,
          status: 'pending',
        },
        { status: 202 },
      ),
    );

    const result = await resumeScan('scan-1');

    // 202 from resume → server flips to running shortly after.
    expect(result.id).toBe('scan-1');
    const call = fetchMock.mock.calls[0]!;
    expect((call[0] as string).endsWith('/scans/scan-1/resume')).toBe(true);
    const init = call[1] as RequestInit;
    expect(init.method).toBe('POST');
    expect((init.headers as Headers).get('X-Requested-With')).toBe('codescan');
  });
});

describe('deleteScan', () => {
  it('DELETEs /scans/{id} with the CSRF header and resolves on 204', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(deleteScan('scan-1')).resolves.toBeUndefined();

    const call = fetchMock.mock.calls[0]!;
    expect((call[0] as string).endsWith('/scans/scan-1')).toBe(true);
    const init = call[1] as RequestInit;
    expect(init.method).toBe('DELETE');
    expect((init.headers as Headers).get('X-Requested-With')).toBe('codescan');
  });
});
