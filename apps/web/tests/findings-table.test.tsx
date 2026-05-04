import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { FindingsTable } from '@/components/findings/findings-table';
import { ApiError } from '@/lib/api/client';
import type { Finding } from '@/lib/api/findings/types';

const { useFindingsInfiniteMock } = vi.hoisted(() => ({
  useFindingsInfiniteMock: vi.fn(),
}));

vi.mock('@/lib/api/findings/use-findings', () => ({
  FINDINGS_QUERY_KEY: 'findings',
  useFindingsInfinite: () => useFindingsInfiniteMock(),
}));

function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    confidence: null,
    file: { id: 'file-1', path: 'src/api/users.py' },
    id: 'f-1',
    line_end: 42,
    line_start: 42,
    message: 'msg',
    recommendation: null,
    rule_id: null,
    scan_type: 'security',
    severity: 'high',
    snippet: null,
    title: 'Hardcoded secret',
    ...overrides,
  };
}

describe('<FindingsTable />', () => {
  it('renders rows from a paginated response and links to the file viewer', () => {
    useFindingsInfiniteMock.mockReturnValue({
      data: {
        pages: [
          {
            items: [
              makeFinding({ id: 'f-1', title: 'A' }),
              makeFinding({
                file: { id: 'file-2', path: 'src/db.py' },
                id: 'f-2',
                title: 'B',
              }),
            ],
            next_cursor: null,
            total: 2,
          },
        ],
        pageParams: [null],
      },
      error: null,
      fetchNextPage: vi.fn(),
      hasNextPage: false,
      isFetchingNextPage: false,
      isPending: false,
      refetch: vi.fn(),
    });

    render(
      <FindingsTable
        scanId="scan-1"
        filters={{ file_id: null, scan_type: [], severity: [] }}
      />,
    );

    expect(screen.getByText('A')).toBeInTheDocument();
    expect(screen.getByText('B')).toBeInTheDocument();
    // File paths render as plain text — the file viewer route lands in T4.3.
    expect(screen.getByText('src/api/users.py').tagName).toBe('SPAN');
    expect(screen.getByText('src/db.py').tagName).toBe('SPAN');
    expect(screen.getByTestId('findings-count-summary')).toHaveTextContent(
      'Showing 2 of 2 findings',
    );
    // No "Load more" when hasNextPage is false.
    expect(screen.queryByTestId('findings-load-more')).not.toBeInTheDocument();
  });

  it('renders the "Load more" button + invokes fetchNextPage when there are more pages', () => {
    const fetchNextPage = vi.fn();
    useFindingsInfiniteMock.mockReturnValue({
      data: {
        pages: [
          {
            items: [makeFinding()],
            next_cursor: 'next',
            total: 87,
          },
        ],
        pageParams: [null],
      },
      error: null,
      fetchNextPage,
      hasNextPage: true,
      isFetchingNextPage: false,
      isPending: false,
      refetch: vi.fn(),
    });

    render(
      <FindingsTable
        scanId="scan-1"
        filters={{ file_id: null, scan_type: [], severity: [] }}
      />,
    );

    expect(screen.getByTestId('findings-count-summary')).toHaveTextContent(
      'Showing 1 of 87 findings',
    );
    fireEvent.click(screen.getByTestId('findings-load-more'));
    expect(fetchNextPage).toHaveBeenCalledTimes(1);
  });

  it('renders the loading state while pending', () => {
    useFindingsInfiniteMock.mockReturnValue({
      data: undefined,
      error: null,
      fetchNextPage: vi.fn(),
      hasNextPage: false,
      isFetchingNextPage: false,
      isPending: true,
      refetch: vi.fn(),
    });

    render(
      <FindingsTable
        scanId="scan-1"
        filters={{ file_id: null, scan_type: [], severity: [] }}
      />,
    );

    expect(screen.getByText('Loading findings…')).toBeInTheDocument();
  });

  it('renders an error panel with a Retry button on error', () => {
    const refetch = vi.fn();
    useFindingsInfiniteMock.mockReturnValue({
      data: undefined,
      error: new ApiError(500, 'server_error', 'Boom.'),
      fetchNextPage: vi.fn(),
      hasNextPage: false,
      isFetchingNextPage: false,
      isPending: false,
      refetch,
    });

    render(
      <FindingsTable
        scanId="scan-1"
        filters={{ file_id: null, scan_type: [], severity: [] }}
      />,
    );

    expect(screen.getByText('Could not load findings.')).toBeInTheDocument();
    expect(screen.getByText('Boom.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it('renders the empty-with-filters state when items is empty and any filter is active', () => {
    useFindingsInfiniteMock.mockReturnValue({
      data: {
        pages: [{ items: [], next_cursor: null, total: 0 }],
        pageParams: [null],
      },
      error: null,
      fetchNextPage: vi.fn(),
      hasNextPage: false,
      isFetchingNextPage: false,
      isPending: false,
      refetch: vi.fn(),
    });

    render(
      <FindingsTable
        scanId="scan-1"
        filters={{ file_id: null, scan_type: [], severity: ['critical'] }}
      />,
    );

    expect(
      screen.getByText('No findings match these filters.'),
    ).toBeInTheDocument();
  });

  it('renders the "no findings" empty state when the scan completed cleanly', () => {
    useFindingsInfiniteMock.mockReturnValue({
      data: {
        pages: [{ items: [], next_cursor: null, total: 0 }],
        pageParams: [null],
      },
      error: null,
      fetchNextPage: vi.fn(),
      hasNextPage: false,
      isFetchingNextPage: false,
      isPending: false,
      refetch: vi.fn(),
    });

    render(
      <FindingsTable
        scanId="scan-1"
        filters={{ file_id: null, scan_type: [], severity: [] }}
      />,
    );

    expect(screen.getByText('No findings.')).toBeInTheDocument();
  });
});
