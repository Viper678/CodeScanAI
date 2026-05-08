import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ScansPage from '@/app/(app)/scans/page';
import { ApiError } from '@/lib/api/auth/errors';
import type { ScanDetail, ScanListResponse } from '@/lib/api/scans/types';

const {
  pushMock,
  rerunScanMock,
  useDeleteScanMutationMock,
  useRerunScanMutationMock,
  useScansFiltersMock,
  useScansQueryMock,
} = vi.hoisted(() => {
  return {
    pushMock: vi.fn(),
    rerunScanMock: vi.fn(),
    useDeleteScanMutationMock: vi.fn(),
    useRerunScanMutationMock: vi.fn(),
    useScansFiltersMock: vi.fn(),
    useScansQueryMock: vi.fn(),
  };
});

vi.mock('next/navigation', () => ({
  usePathname: () => '/scans',
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/lib/api/scans/use-scans', () => ({
  useDeleteScanMutation: () => useDeleteScanMutationMock(),
  useRerunScanMutation: () => useRerunScanMutationMock(),
  useScansQuery: (params: unknown) => useScansQueryMock(params),
}));

vi.mock('@/lib/api/scans/use-scans-filters', () => ({
  useScansFilters: () => useScansFiltersMock(),
}));

function makeScan(overrides: Partial<ScanDetail> = {}): ScanDetail {
  return {
    created_at: '2026-05-01T12:00:00Z',
    error: null,
    finished_at: null,
    id: 'scan-1',
    name: 'Nightly security scan',
    progress_done: 47,
    progress_total: 312,
    scan_types: ['security', 'bugs'],
    started_at: '2026-05-01T12:00:00Z',
    status: 'running',
    summary: { by_severity: {}, by_type: {} },
    upload_id: 'upload-1',
    ...overrides,
  };
}

function makeListResult(items: ScanDetail[]): {
  data: ScanListResponse;
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

function setUpFilters(status: string[] = []) {
  useScansFiltersMock.mockReturnValue({
    clearAll: vi.fn(),
    filters: { status },
    setFilters: vi.fn(),
    toggleStatus: vi.fn(),
  });
}

function setUpRerunMutation(impl?: {
  isPending?: boolean;
  mutate?: typeof rerunScanMock;
}) {
  useRerunScanMutationMock.mockReturnValue({
    isPending: impl?.isPending ?? false,
    mutate: impl?.mutate ?? rerunScanMock,
  });
}

describe('ScansPage', () => {
  beforeEach(() => {
    pushMock.mockReset();
    rerunScanMock.mockReset();
    useDeleteScanMutationMock.mockReset();
    useDeleteScanMutationMock.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    });
    useRerunScanMutationMock.mockReset();
    useScansFiltersMock.mockReset();
    useScansQueryMock.mockReset();
  });

  it('renders a row per scan', () => {
    setUpFilters();
    setUpRerunMutation();
    useScansQueryMock.mockReturnValue(
      makeListResult([
        makeScan({ id: 's-1', name: 'Repo audit' }),
        makeScan({
          id: 's-2',
          name: null,
          progress_done: 312,
          progress_total: 312,
          status: 'completed',
        }),
      ]),
    );

    render(<ScansPage />);

    expect(screen.getByText('Repo audit')).toBeInTheDocument();
    expect(screen.getByText('Unnamed scan')).toBeInTheDocument();

    const firstRow = screen.getByTestId('scan-row-s-1');
    // Open-link is now an absolute overlay anchor inside the row, not the
    // row itself — assert the anchor is present and points at the right id.
    expect(firstRow.querySelector(`a[href="/scans/s-1"]`)).toBeInTheDocument();
    const secondRow = screen.getByTestId('scan-row-s-2');
    expect(secondRow.querySelector(`a[href="/scans/s-2"]`)).toBeInTheDocument();

    // Non-terminal shows the progress text; terminal shows '—'.
    expect(firstRow).toHaveTextContent('47 / 312');
    expect(secondRow).toHaveTextContent('—');
  });

  it('only shows the Re-run button on terminal-status rows', () => {
    setUpFilters();
    setUpRerunMutation();
    useScansQueryMock.mockReturnValue(
      makeListResult([
        makeScan({ id: 's-pending', status: 'pending' }),
        makeScan({ id: 's-running', status: 'running' }),
        makeScan({ id: 's-completed', status: 'completed' }),
        makeScan({ id: 's-failed', status: 'failed' }),
        makeScan({ id: 's-cancelled', status: 'cancelled' }),
      ]),
    );

    render(<ScansPage />);

    expect(
      screen.queryByTestId('scan-row-s-pending-rerun'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('scan-row-s-running-rerun'),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId('scan-row-s-completed-rerun'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('scan-row-s-failed-rerun')).toBeInTheDocument();
    expect(
      screen.getByTestId('scan-row-s-cancelled-rerun'),
    ).toBeInTheDocument();
  });

  it('calls the re-run mutation and routes to the new scan on success', async () => {
    setUpFilters();
    const mutate = vi.fn(
      (
        sourceId: string,
        opts?: {
          onSuccess?: (data: { id: string }) => void;
          onError?: (err: ApiError) => void;
        },
      ) => {
        // Simulate a successful 202 with a brand-new scan id.
        opts?.onSuccess?.({ id: `${sourceId}-rerun` });
      },
    );
    setUpRerunMutation({ mutate });
    useScansQueryMock.mockReturnValue(
      makeListResult([makeScan({ id: 's-1', status: 'completed' })]),
    );

    render(<ScansPage />);

    fireEvent.click(screen.getByTestId('scan-row-s-1-rerun'));

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0]![0]).toBe('s-1');
    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith('/scans/s-1-rerun');
    });
  });

  it('surfaces an inline error when the re-run mutation fails with unprocessable_rerun', async () => {
    setUpFilters();
    const mutate = vi.fn(
      (
        _sourceId: string,
        opts?: {
          onSuccess?: (data: { id: string }) => void;
          onError?: (err: ApiError) => void;
        },
      ) => {
        opts?.onError?.(
          new ApiError(422, 'unprocessable_rerun', 'no scannable files'),
        );
      },
    );
    setUpRerunMutation({ mutate });
    useScansQueryMock.mockReturnValue(
      makeListResult([makeScan({ id: 's-1', status: 'failed' })]),
    );

    render(<ScansPage />);

    fireEvent.click(screen.getByTestId('scan-row-s-1-rerun'));

    await waitFor(() => {
      expect(screen.getByTestId('scan-row-s-1-rerun-error')).toHaveTextContent(
        /source can no longer be re-run/i,
      );
    });
    // No navigation on failure.
    expect(pushMock).not.toHaveBeenCalled();
  });

  it('forwards the active status filter into the scans query', () => {
    setUpFilters(['running', 'completed']);
    setUpRerunMutation();
    useScansQueryMock.mockReturnValue(makeListResult([]));

    render(<ScansPage />);

    const lastCall =
      useScansQueryMock.mock.calls[useScansQueryMock.mock.calls.length - 1]!;
    expect(lastCall[0]).toMatchObject({ status: ['running', 'completed'] });
  });

  it('renders the EmptyState when the response has zero items', () => {
    setUpFilters();
    setUpRerunMutation();
    useScansQueryMock.mockReturnValue(makeListResult([]));

    render(<ScansPage />);

    expect(
      screen.getByRole('heading', { name: 'No scans yet' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Run your first scan' }),
    ).toBeInTheDocument();
  });

  it('renders a filter-specific empty state when filters are active and no rows match', () => {
    setUpFilters(['failed']);
    setUpRerunMutation();
    useScansQueryMock.mockReturnValue(makeListResult([]));

    render(<ScansPage />);

    expect(
      screen.getByRole('heading', { name: 'No scans match these filters' }),
    ).toBeInTheDocument();
    // Should not offer the "Run your first scan" CTA — they have history,
    // they just filtered it out.
    expect(
      screen.queryByRole('link', { name: 'Run your first scan' }),
    ).not.toBeInTheDocument();
  });

  it('shows the loading skeleton while pending', () => {
    setUpFilters();
    setUpRerunMutation();
    useScansQueryMock.mockReturnValue({
      data: undefined,
      error: null,
      isPending: true,
      refetch: vi.fn(),
    });

    render(<ScansPage />);

    expect(screen.getByText('Loading scans…')).toBeInTheDocument();
  });

  it('renders the error panel with a Retry button on error', () => {
    setUpFilters();
    setUpRerunMutation();
    useScansQueryMock.mockReturnValue({
      data: undefined,
      error: new ApiError(500, 'server_error', 'Boom.'),
      isPending: false,
      refetch: vi.fn(),
    });

    render(<ScansPage />);

    expect(screen.getByText('Could not load scans.')).toBeInTheDocument();
    expect(screen.getByText('Boom.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
