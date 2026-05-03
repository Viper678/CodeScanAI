import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useUploadPolling } from '@/lib/api/uploads/use-upload';
import type { Upload } from '@/lib/api/uploads/types';

const { fetchUploadMock } = vi.hoisted(() => ({
  fetchUploadMock: vi.fn(),
}));

vi.mock('@/lib/api/uploads/client', () => ({
  fetchUpload: (id: string, signal?: AbortSignal) =>
    fetchUploadMock(id, signal),
  uploadFile: vi.fn(),
}));

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

function makeUpload(overrides: Partial<Upload> = {}): Upload {
  return {
    created_at: '2026-01-01T00:00:00Z',
    error: null,
    file_count: 0,
    id: 'upload-1',
    kind: 'zip',
    original_name: 'r.zip',
    scannable_count: 0,
    size_bytes: 1,
    status: 'extracting',
    ...overrides,
  };
}

afterEach(() => {
  fetchUploadMock.mockReset();
});

describe('useUploadPolling', () => {
  it('fires onReady once and stops polling when status becomes ready', async () => {
    fetchUploadMock.mockResolvedValue(
      makeUpload({ file_count: 12, status: 'ready' }),
    );
    const onReady = vi.fn();
    const onFailed = vi.fn();

    renderHook(
      () =>
        useUploadPolling('upload-1', {
          enabled: true,
          onFailed,
          onReady,
        }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      expect(onReady).toHaveBeenCalledTimes(1);
    });
    expect(onReady.mock.calls[0]?.[0]).toMatchObject({
      file_count: 12,
      status: 'ready',
    });
    expect(onFailed).not.toHaveBeenCalled();

    // After a beat, no further fetches should fire (interval cleared).
    const callsAfterReady = fetchUploadMock.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(fetchUploadMock.mock.calls.length).toBe(callsAfterReady);
  });

  it('fires onFailed once and stops polling when status becomes failed', async () => {
    fetchUploadMock.mockResolvedValue(
      makeUpload({ error: 'zip bomb detected', status: 'failed' }),
    );
    const onReady = vi.fn();
    const onFailed = vi.fn();

    renderHook(
      () =>
        useUploadPolling('upload-1', {
          enabled: true,
          onFailed,
          onReady,
        }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      expect(onFailed).toHaveBeenCalledTimes(1);
    });
    expect(onFailed.mock.calls[0]?.[0]).toMatchObject({
      error: 'zip bomb detected',
      status: 'failed',
    });
    expect(onReady).not.toHaveBeenCalled();
  });

  it('does not fetch when uploadId is null or polling is disabled', async () => {
    const { rerender } = renderHook(
      ({ id, enabled }: { id: string | null; enabled: boolean }) =>
        useUploadPolling(id, { enabled }),
      {
        initialProps: { enabled: true, id: null as string | null },
        wrapper: makeWrapper(),
      },
    );

    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(fetchUploadMock).not.toHaveBeenCalled();

    rerender({ enabled: false, id: 'upload-1' });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(fetchUploadMock).not.toHaveBeenCalled();
  });
});
