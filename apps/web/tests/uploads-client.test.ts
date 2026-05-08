import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { deleteUpload, fetchUploads } from '@/lib/api/uploads/client';

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

describe('fetchUploads', () => {
  it('clamps the limit and forwards the offset on the wire', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], next_cursor: null, total: 0 }),
    );

    await fetchUploads({ limit: 9_999, offset: 25 });

    const url = fetchMock.mock.calls[0]![0] as string;
    const search = new URL(url).searchParams;
    expect(search.get('limit')).toBe('100');
    expect(search.get('offset')).toBe('25');
  });
});

describe('deleteUpload', () => {
  it('DELETEs /uploads/{id} with the CSRF header and resolves on 204', async () => {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(deleteUpload('u-1')).resolves.toBeUndefined();

    const call = fetchMock.mock.calls[0]!;
    expect((call[0] as string).endsWith('/uploads/u-1')).toBe(true);
    const init = call[1] as RequestInit;
    expect(init.method).toBe('DELETE');
    expect((init.headers as Headers).get('X-Requested-With')).toBe('codescan');
  });
});
