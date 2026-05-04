import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import ScansPage from '@/app/(app)/scans/page';
import { ApiError } from '@/lib/api/auth/errors';
import type { ScanDetail, ScanListResponse } from '@/lib/api/scans/types';

const { useScansQueryMock } = vi.hoisted(() => ({
  useScansQueryMock: vi.fn(),
}));

vi.mock('@/lib/api/scans/use-scans', () => ({
  useScansQuery: () => useScansQueryMock(),
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

describe('ScansPage', () => {
  it('renders a row per scan and links to the progress page', () => {
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
    expect(firstRow).toHaveAttribute('href', '/scans/s-1');
    expect(screen.getByTestId('scan-row-s-2')).toHaveAttribute(
      'href',
      '/scans/s-2',
    );

    // Non-terminal shows the progress text; terminal shows '—'.
    expect(firstRow).toHaveTextContent('47 / 312');
    expect(screen.getByTestId('scan-row-s-2')).toHaveTextContent('—');
  });

  it('renders the EmptyState when the response has zero items', () => {
    useScansQueryMock.mockReturnValue(makeListResult([]));

    render(<ScansPage />);

    expect(
      screen.getByRole('heading', { name: 'No scans yet' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Run your first scan' }),
    ).toBeInTheDocument();
  });

  it('shows the loading skeleton while pending', () => {
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
