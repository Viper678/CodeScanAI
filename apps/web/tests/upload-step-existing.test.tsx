import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { UploadStep } from '@/components/upload/upload-step';
import type { UploadDetail, UploadListResponse } from '@/lib/api/uploads/types';

// Mock the upload hooks: we never want the test to hit a real fetch.
// ``useUploadMutation`` / ``useUploadPolling`` are stubbed to no-ops since
// the new-mode flow isn't what this file is exercising — that already
// has coverage in ``upload-client.test.ts`` and the e2e suite.
const { useUploadMutationMock, useUploadPollingMock, useUploadsQueryMock } =
  vi.hoisted(() => ({
    useUploadMutationMock: vi.fn(),
    useUploadPollingMock: vi.fn(),
    useUploadsQueryMock: vi.fn(),
  }));

vi.mock('@/lib/api/uploads/use-upload', () => ({
  useUploadMutation: () => useUploadMutationMock(),
  useUploadPolling: useUploadPollingMock,
  useUploadsQuery: () => useUploadsQueryMock(),
}));

function makeUpload(overrides: Partial<UploadDetail> = {}): UploadDetail {
  return {
    created_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    error: null,
    file_count: 200,
    id: 'upload-existing-1',
    kind: 'zip',
    original_name: 'my-repo.zip',
    scannable_count: 50,
    size_bytes: 2_000_000,
    status: 'ready',
    ...overrides,
  };
}

beforeEach(() => {
  useUploadMutationMock.mockReturnValue({
    mutate: vi.fn(),
    reset: vi.fn(),
  });
  useUploadPollingMock.mockReturnValue(undefined);
  useUploadsQueryMock.mockReset();
});

describe('UploadStep — existing-upload mode', () => {
  it('defaults to "new" mode (dropzone visible, list hidden)', () => {
    useUploadsQueryMock.mockReturnValue({
      data: { items: [], next_cursor: null, total: 0 } as UploadListResponse,
      error: null,
      isError: false,
      isPending: false,
    });

    render(<UploadStep onReady={vi.fn()} />);

    // "Upload new" toggle is selected, dropzone is rendered.
    expect(screen.getByTestId('upload-mode-new')).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.queryByTestId('existing-uploads-list')).toBeNull();
  });

  it('shows the ready uploads list when "Use existing" is selected', () => {
    useUploadsQueryMock.mockReturnValue({
      data: {
        items: [
          makeUpload(),
          makeUpload({ id: 'upload-existing-2', original_name: 'other.zip' }),
        ],
        next_cursor: null,
        total: 2,
      } as UploadListResponse,
      error: null,
      isError: false,
      isPending: false,
    });

    render(<UploadStep onReady={vi.fn()} />);
    fireEvent.click(screen.getByTestId('upload-mode-existing'));

    expect(screen.getByTestId('existing-uploads-list')).toBeInTheDocument();
    expect(screen.getByText('my-repo.zip')).toBeInTheDocument();
    expect(screen.getByText('other.zip')).toBeInTheDocument();
  });

  it('shows the empty state when no ready uploads are returned', () => {
    // After Codex P2 follow-up: the hook requests ``status=ready`` on the
    // server, so the API only ever returns ready rows here. A single
    // ``existing-uploads-empty`` state covers both "no uploads at all"
    // and "all uploads are still extracting/failed" — the wizard can't
    // distinguish, and the user-facing copy doesn't need to.
    useUploadsQueryMock.mockReturnValue({
      data: { items: [], next_cursor: null, total: 0 } as UploadListResponse,
      error: null,
      isError: false,
      isPending: false,
    });

    render(<UploadStep onReady={vi.fn()} />);
    fireEvent.click(screen.getByTestId('upload-mode-existing'));

    expect(screen.getByTestId('existing-uploads-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('existing-uploads-list')).toBeNull();
  });

  it('clicking "Use" invokes onReady with the picked upload', () => {
    const upload = makeUpload();
    useUploadsQueryMock.mockReturnValue({
      data: {
        items: [upload],
        next_cursor: null,
        total: 1,
      } as UploadListResponse,
      error: null,
      isError: false,
      isPending: false,
    });
    const onReady = vi.fn();

    render(<UploadStep onReady={onReady} />);
    fireEvent.click(screen.getByTestId('upload-mode-existing'));
    fireEvent.click(screen.getByTestId(`existing-upload-use-${upload.id}`));

    expect(onReady).toHaveBeenCalledTimes(1);
    expect(onReady).toHaveBeenCalledWith(upload);
  });

  it('surfaces a load error', () => {
    useUploadsQueryMock.mockReturnValue({
      data: undefined,
      error: new Error('boom'),
      isError: true,
      isPending: false,
    });

    render(<UploadStep onReady={vi.fn()} />);
    fireEvent.click(screen.getByTestId('upload-mode-existing'));

    expect(screen.getByTestId('existing-uploads-error')).toBeInTheDocument();
  });

  it('shows a loading state while fetching', () => {
    useUploadsQueryMock.mockReturnValue({
      data: undefined,
      error: null,
      isError: false,
      isPending: true,
    });

    render(<UploadStep onReady={vi.fn()} />);
    fireEvent.click(screen.getByTestId('upload-mode-existing'));

    expect(screen.getByTestId('existing-uploads-loading')).toBeInTheDocument();
  });
});
