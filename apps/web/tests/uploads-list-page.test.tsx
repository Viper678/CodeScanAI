import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import UploadsPage from '@/app/(app)/uploads/page';
import { ApiError } from '@/lib/api/auth/errors';
import type { UploadDetail, UploadListResponse } from '@/lib/api/uploads/types';

const { useDeleteUploadMutationMock, useUploadsQueryMock } = vi.hoisted(() => ({
  useDeleteUploadMutationMock: vi.fn(),
  useUploadsQueryMock: vi.fn(),
}));

vi.mock('@/lib/api/uploads/use-upload', () => ({
  useDeleteUploadMutation: () => useDeleteUploadMutationMock(),
  useUploadsQuery: () => useUploadsQueryMock(),
}));

beforeEach(() => {
  useDeleteUploadMutationMock.mockReturnValue({
    isPending: false,
    mutate: vi.fn(),
  });
});

function makeUpload(overrides: Partial<UploadDetail> = {}): UploadDetail {
  return {
    created_at: '2026-05-01T12:00:00Z',
    error: null,
    file_count: 312,
    id: 'upload-1',
    kind: 'zip',
    original_name: 'monorepo.zip',
    scannable_count: 280,
    size_bytes: 1.2 * 1024 * 1024,
    status: 'ready',
    ...overrides,
  };
}

function makeListResult(items: UploadDetail[]): {
  data: UploadListResponse;
  error: null;
  isPending: false;
  refetch: () => Promise<unknown>;
} {
  return {
    data: { items, next_cursor: null, total: items.length },
    error: null,
    isPending: false,
    refetch: vi.fn(),
  };
}

describe('UploadsPage', () => {
  it('renders a row per upload and links to the tree-preview', () => {
    useUploadsQueryMock.mockReturnValue(
      makeListResult([
        makeUpload({ id: 'u-1', original_name: 'monorepo.zip' }),
        makeUpload({
          file_count: null,
          id: 'u-2',
          original_name: 'wip.zip',
          status: 'extracting',
        }),
      ]),
    );

    render(<UploadsPage />);

    expect(screen.getByText('monorepo.zip')).toBeInTheDocument();
    expect(screen.getByText('wip.zip')).toBeInTheDocument();

    // Row is no longer the anchor itself — the link is now an absolute
    // overlay inside the row (so the row can host action buttons like
    // Delete). Assert the overlay anchor exists with the right href.
    const firstRow = screen.getByTestId('upload-row-u-1');
    expect(
      firstRow.querySelector(`a[href="/uploads/u-1/tree-preview"]`),
    ).toBeInTheDocument();
    const secondRow = screen.getByTestId('upload-row-u-2');
    expect(
      secondRow.querySelector(`a[href="/uploads/u-2/tree-preview"]`),
    ).toBeInTheDocument();

    // Ready upload shows file count; extracting shows "—".
    expect(firstRow).toHaveTextContent('312 files');
    expect(secondRow).toHaveTextContent('—');
  });

  it('renders the EmptyState when the response has zero items', () => {
    useUploadsQueryMock.mockReturnValue(makeListResult([]));

    render(<UploadsPage />);

    expect(
      screen.getByRole('heading', { name: 'No uploads yet' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Upload your first repo' }),
    ).toBeInTheDocument();
  });

  it('shows the loading skeleton while pending', () => {
    useUploadsQueryMock.mockReturnValue({
      data: undefined,
      error: null,
      isPending: true,
      refetch: vi.fn(),
    });

    render(<UploadsPage />);

    expect(screen.getByText('Loading uploads…')).toBeInTheDocument();
  });

  it('renders the error panel with a Retry button on error', () => {
    useUploadsQueryMock.mockReturnValue({
      data: undefined,
      error: new ApiError(500, 'server_error', 'Boom.'),
      isPending: false,
      refetch: vi.fn(),
    });

    render(<UploadsPage />);

    expect(screen.getByText('Could not load uploads.')).toBeInTheDocument();
    expect(screen.getByText('Boom.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
