import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { FindingsTable } from '@/components/findings/findings-table';
import { ApiError } from '@/lib/api/client';
import type { Finding } from '@/lib/api/findings/types';

const { useFindingsInfiniteMock } = vi.hoisted(() => ({
  useFindingsInfiniteMock: vi.fn(),
}));

vi.mock('@/lib/api/findings/use-findings', () => ({
  FINDINGS_FOR_FILE_QUERY_KEY: 'findings-for-file',
  FINDINGS_QUERY_KEY: 'findings',
  useFindingsForFile: vi.fn(),
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

function renderTable(
  props: {
    scanId?: string;
    uploadId?: string;
    filters?: { severity: []; scan_type: []; file_id: null };
  } = {},
) {
  return render(
    <FindingsTable
      scanId={props.scanId ?? 'scan-1'}
      uploadId={props.uploadId ?? 'upload-1'}
      filters={props.filters ?? { file_id: null, scan_type: [], severity: [] }}
    />,
  );
}

describe('<FindingsTable />', () => {
  it('renders rows from a paginated response and links each path to the file viewer', () => {
    useFindingsInfiniteMock.mockReturnValue({
      data: {
        pages: [
          {
            items: [
              makeFinding({
                id: 'f-1',
                line_start: 42,
                title: 'A',
              }),
              makeFinding({
                file: { id: 'file-2', path: 'src/db.py' },
                id: 'f-2',
                // line_start: null exercises the "no &line=" branch.
                line_start: null,
                line_end: null,
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

    renderTable();

    expect(screen.getByText('A')).toBeInTheDocument();
    expect(screen.getByText('B')).toBeInTheDocument();

    const linkA = screen.getByRole('link', { name: 'src/api/users.py' });
    expect(linkA).toHaveAttribute(
      'href',
      '/uploads/upload-1/files/file-1?scan_id=scan-1&line=42',
    );
    // line_start=null → href omits the `line` param entirely.
    const linkB = screen.getByRole('link', { name: 'src/db.py' });
    expect(linkB).toHaveAttribute(
      'href',
      '/uploads/upload-1/files/file-2?scan_id=scan-1',
    );

    expect(screen.getByTestId('findings-count-summary')).toHaveTextContent(
      'Showing 2 of 2 findings',
    );
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

    renderTable();

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

    renderTable();

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

    renderTable();

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

    renderTable({
      filters: {
        file_id: null,
        scan_type: [],
        severity: ['critical'],
      } as never,
    });

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

    renderTable();

    expect(screen.getByText('No findings.')).toBeInTheDocument();
  });
});
