import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/client';

const { useFileContentMock, useFindingsForFileMock } = vi.hoisted(() => ({
  useFileContentMock: vi.fn(),
  useFindingsForFileMock: vi.fn(),
}));

vi.mock('@/lib/api/file-content/use-file-content', () => ({
  FILE_CONTENT_QUERY_KEY: 'file-content',
  useFileContent: () => useFileContentMock(),
}));

vi.mock('@/lib/api/findings/use-findings', () => ({
  FINDINGS_FOR_FILE_QUERY_KEY: 'findings-for-file',
  FINDINGS_QUERY_KEY: 'findings',
  useFindingsForFile: () => useFindingsForFileMock(),
  useFindingsInfinite: () => ({
    data: undefined,
    error: null,
    fetchNextPage: vi.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
    isPending: false,
    refetch: vi.fn(),
  }),
}));

// Replace next/dynamic with an immediate passthrough so the editor renders
// synchronously in jsdom. The real loader returns a lazy component.
vi.mock('next/dynamic', () => ({
  __esModule: true,
  default: (loader: () => Promise<unknown>) => {
    function DynamicMock(props: Record<string, unknown>) {
      const target = props.scrollTarget as
        | { line: number; nonce: number }
        | null
        | undefined;
      return (
        <div
          data-testid="code-editor-mock"
          data-scroll-line={target ? String(target.line) : 'null'}
          data-scroll-nonce={target ? String(target.nonce) : 'null'}
        >
          {String(props.content ?? '')}
          (line={target ? String(target.line) : 'null'})
        </div>
      );
    }
    // Eager-call the loader so the import side-effects (if any) run; we
    // ignore the result.
    void loader().catch(() => undefined);
    return DynamicMock;
  },
}));

import { FileViewerPage } from '@/components/file-viewer/file-viewer-page';

function setMocks({
  content = "print('hi')",
  contentError = null as ApiError | null,
  contentLoading = false,
  findings = [] as Array<Record<string, unknown>>,
  findingsLoading = false,
}: Partial<{
  content: string | undefined;
  contentError: ApiError | null;
  contentLoading: boolean;
  findings: Array<Record<string, unknown>>;
  findingsLoading: boolean;
}>) {
  useFileContentMock.mockReturnValue({
    data: contentLoading || contentError ? undefined : content,
    error: contentError,
    isPending: contentLoading,
  });
  useFindingsForFileMock.mockReturnValue({
    data: findingsLoading
      ? undefined
      : { items: findings, next_cursor: null, total: findings.length },
    error: null,
    isPending: findingsLoading,
  });
}

describe('<FileViewerPage />', () => {
  it('renders the editor and a per-file sidebar when a scan_id is supplied', () => {
    setMocks({
      content: 'def main(): pass\n',
      findings: [
        {
          confidence: null,
          file: { id: 'file-1', path: 'src/main.py' },
          id: 'f-1',
          line_end: 10,
          line_start: 10,
          message: 'm',
          recommendation: null,
          rule_id: null,
          scan_type: 'security',
          severity: 'high',
          snippet: null,
          title: 'A finding',
        },
      ],
    });

    render(
      <FileViewerPage
        uploadId="u-1"
        fileId="file-1"
        scanId="scan-1"
        initialLine={10}
      />,
    );

    expect(screen.getByTestId('code-editor-mock')).toHaveTextContent(
      'def main(): pass',
    );
    expect(screen.getByTestId('code-editor-mock')).toHaveTextContent('line=10');
    expect(screen.getByText('Findings (1)')).toBeInTheDocument();
    expect(screen.getByText('A finding')).toBeInTheDocument();
    expect(screen.getByTestId('viewer-file-path')).toHaveTextContent(
      'src/main.py',
    );
  });

  it('renders a hint sidebar when scan_id is absent', () => {
    setMocks({ content: 'x = 1\n' });

    render(
      <FileViewerPage
        uploadId="u-1"
        fileId="file-1"
        scanId={null}
        initialLine={null}
      />,
    );

    expect(
      screen.getByText(
        'Open a file from a scan results page to see its findings here.',
      ),
    ).toBeInTheDocument();
  });

  it('renders the 413 fallback for too-large files', () => {
    setMocks({
      content: undefined,
      contentError: new ApiError(413, 'payload_too_large', 'too big'),
    });

    render(
      <FileViewerPage
        uploadId="u-1"
        fileId="file-1"
        scanId="scan-1"
        initialLine={null}
      />,
    );

    expect(
      screen.getByText('File is too large to preview.'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('viewer-fallback')).toBeInTheDocument();
  });

  it('renders the 415 fallback for binary files', () => {
    setMocks({
      content: undefined,
      contentError: new ApiError(
        415,
        'unsupported_media_type',
        'binary_file_not_viewable',
      ),
    });

    render(
      <FileViewerPage
        uploadId="u-1"
        fileId="file-1"
        scanId="scan-1"
        initialLine={null}
      />,
    );

    expect(
      screen.getByText('Binary file — preview not supported.'),
    ).toBeInTheDocument();
  });

  it('shows a loading state while content is pending', () => {
    setMocks({ content: undefined, contentLoading: true });

    render(
      <FileViewerPage
        uploadId="u-1"
        fileId="file-1"
        scanId="scan-1"
        initialLine={null}
      />,
    );

    expect(screen.getByTestId('editor-loading')).toBeInTheDocument();
  });

  it('bumps scroll nonce on every sidebar click — even repeats (codex P2)', () => {
    // Clicking the same finding twice in a row must still re-fire the
    // editor's scroll effect. The bug: storing only `line: number` made
    // React skip the state update on identical primitives, so the editor
    // never re-scrolled after manual scrolling away. Fix: pair the line
    // with a per-click nonce so object identity changes every time.
    const finding = {
      confidence: null,
      file: { id: 'file-1', path: 'src/main.py' },
      id: 'f-1',
      line_end: 10,
      line_start: 10,
      message: 'm',
      recommendation: null,
      rule_id: null,
      scan_type: 'security',
      severity: 'high',
      snippet: null,
      title: 'A finding',
    };
    setMocks({ content: 'def main(): pass\n', findings: [finding] });

    render(
      <FileViewerPage
        uploadId="u-1"
        fileId="file-1"
        scanId="scan-1"
        initialLine={null}
      />,
    );

    const editor = screen.getByTestId('code-editor-mock');
    expect(editor.dataset.scrollNonce).toBe('null');

    fireEvent.click(screen.getByTestId('sidebar-item-f-1'));
    expect(editor.dataset.scrollLine).toBe('10');
    const firstNonce = Number.parseInt(editor.dataset.scrollNonce ?? '0', 10);
    expect(firstNonce).toBeGreaterThan(0);

    fireEvent.click(screen.getByTestId('sidebar-item-f-1'));
    const secondNonce = Number.parseInt(editor.dataset.scrollNonce ?? '0', 10);
    expect(secondNonce).toBeGreaterThan(firstNonce);
    expect(editor.dataset.scrollLine).toBe('10');
  });
});
