import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import UploadsPage from '@/app/(app)/uploads/page';
import { ApiError } from '@/lib/api/auth/errors';
import type { UploadDetail, UploadListResponse } from '@/lib/api/uploads/types';

const {
  deleteUploadMock,
  useDeleteUploadMutationMock,
  useUploadDeleteImpactMock,
  useUploadsQueryMock,
} = vi.hoisted(() => ({
  deleteUploadMock: vi.fn(),
  useDeleteUploadMutationMock: vi.fn(),
  useUploadDeleteImpactMock: vi.fn(),
  useUploadsQueryMock: vi.fn(),
}));

vi.mock('@/lib/api/uploads/use-upload', () => ({
  useDeleteUploadMutation: () => useDeleteUploadMutationMock(),
  useUploadDeleteImpact: (
    uploadId: string | undefined,
    opts: { enabled: boolean },
  ) => useUploadDeleteImpactMock(uploadId, opts),
  useUploadsQuery: () => useUploadsQueryMock(),
}));

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
  beforeEach(() => {
    deleteUploadMock.mockReset();
    deleteUploadMock.mockResolvedValue(undefined);
    useDeleteUploadMutationMock.mockReset();
    useDeleteUploadMutationMock.mockReturnValue({
      isPending: false,
      mutateAsync: deleteUploadMock,
    });
    useUploadDeleteImpactMock.mockReset();
    useUploadDeleteImpactMock.mockReturnValue({
      data: undefined,
      isError: false,
      isFetching: false,
    });
    useUploadsQueryMock.mockReset();
  });

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

    // The row is now a div with an absolute overlay anchor (so the inline
    // delete button can sit above it without nesting button-in-anchor). Look
    // up the link inside the row rather than treating the row itself as the
    // <a>.
    const firstRow = screen.getByTestId('upload-row-u-1');
    expect(
      firstRow.querySelector('a[href="/uploads/u-1/tree-preview"]'),
    ).toBeInTheDocument();
    const secondRow = screen.getByTestId('upload-row-u-2');
    expect(
      secondRow.querySelector('a[href="/uploads/u-2/tree-preview"]'),
    ).toBeInTheDocument();

    // Ready upload shows file count; extracting shows "—".
    expect(firstRow).toHaveTextContent('312 files');
    expect(secondRow).toHaveTextContent('—');
  });

  it('exposes the delete trigger on every row and fires the mutation on confirm', async () => {
    useUploadsQueryMock.mockReturnValue(
      makeListResult([
        makeUpload({ id: 'u-1', original_name: 'monorepo.zip' }),
      ]),
    );

    render(<UploadsPage />);

    fireEvent.click(screen.getByTestId('upload-row-u-1-delete-trigger'));
    fireEvent.click(screen.getByTestId('upload-row-u-1-delete-confirm'));

    await waitFor(() => {
      expect(deleteUploadMock).toHaveBeenCalledWith('u-1');
    });
  });

  it('warns the user that scans and findings cascade when delete is armed', () => {
    useUploadsQueryMock.mockReturnValue(
      makeListResult([
        makeUpload({ id: 'u-1', original_name: 'monorepo.zip' }),
      ]),
    );
    useUploadDeleteImpactMock.mockReturnValue({
      data: { complete: true, findingCount: 17, scanCount: 3 },
      isError: false,
      isFetching: false,
    });

    render(<UploadsPage />);

    // Idle: no description rendered yet.
    expect(
      screen.queryByTestId('upload-row-u-1-delete-description'),
    ).toBeNull();

    // Arm the destructive action — flips description on with concrete counts.
    fireEvent.click(screen.getByTestId('upload-row-u-1-delete-trigger'));

    const description = screen.getByTestId('upload-row-u-1-delete-description');
    expect(description).toBeInTheDocument();
    expect(description.textContent).toMatch(
      /also permanently remove its 3 scans and 17 findings/i,
    );
    expect(description.textContent).toMatch(/cannot be undone/i);
  });

  it('shows the no-counts fallback when there are more scans than we paged', () => {
    // The hook caps at limit=100 — when the upload has more rows than that,
    // ``complete: false`` is the signal to drop exact numbers rather than
    // *understate* the cascade. The user sees the generic "any scans and
    // findings" copy instead of a misleading lower-bound.
    useUploadsQueryMock.mockReturnValue(
      makeListResult([makeUpload({ id: 'u-1', original_name: 'mega.zip' })]),
    );
    useUploadDeleteImpactMock.mockReturnValue({
      data: { complete: false, findingCount: 250, scanCount: 137 },
      isError: false,
      isFetching: false,
    });

    render(<UploadsPage />);
    fireEvent.click(screen.getByTestId('upload-row-u-1-delete-trigger'));

    const description = screen.getByTestId('upload-row-u-1-delete-description');
    expect(description.textContent).toMatch(
      /any scans and findings associated with it/i,
    );
    // Concrete numbers must not leak through when we can't trust them.
    expect(description.textContent).not.toMatch(/137|250/);
  });

  it('renders the loading copy while a re-armed fetch is in flight', () => {
    // After cancelling + re-arming, React Query keeps the previous result in
    // ``data`` while the refetch is in flight. The helper must use the
    // ``isFetching`` flag (not the initial-load-only ``isLoading``) so stale
    // cached numbers can't leak into the warning during that window.
    useUploadsQueryMock.mockReturnValue(
      makeListResult([makeUpload({ id: 'u-1', original_name: 'stale.zip' })]),
    );
    useUploadDeleteImpactMock.mockReturnValue({
      data: { complete: true, findingCount: 99, scanCount: 9 },
      isError: false,
      isFetching: true,
    });

    render(<UploadsPage />);
    fireEvent.click(screen.getByTestId('upload-row-u-1-delete-trigger'));

    const description = screen.getByTestId('upload-row-u-1-delete-description');
    // Ellipsis stand-ins, not the stale 9/99 from the previous fetch.
    expect(description.textContent).not.toMatch(/9 scans|99 findings/);
    expect(description.textContent).toContain('…');
  });

  it('surfaces an inline error when the delete mutation rejects', async () => {
    deleteUploadMock.mockRejectedValueOnce(
      new ApiError(500, 'server_error', 'Boom.'),
    );
    useUploadsQueryMock.mockReturnValue(
      makeListResult([makeUpload({ id: 'u-1' })]),
    );

    render(<UploadsPage />);

    fireEvent.click(screen.getByTestId('upload-row-u-1-delete-trigger'));
    fireEvent.click(screen.getByTestId('upload-row-u-1-delete-confirm'));

    await waitFor(() => {
      expect(
        screen.getByTestId('upload-row-u-1-delete-error'),
      ).toHaveTextContent(/boom/i);
    });
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
