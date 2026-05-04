import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SnippetViewer } from '@/components/findings/snippet-viewer';

describe('<SnippetViewer />', () => {
  it('numbers lines starting from startLine', () => {
    render(
      <SnippetViewer
        snippet={'line a\nline b\nline c'}
        startLine={42}
        lineStart={42}
        lineEnd={42}
      />,
    );

    expect(screen.getByTestId('snippet-line-42')).toBeInTheDocument();
    expect(screen.getByTestId('snippet-line-43')).toBeInTheDocument();
    expect(screen.getByTestId('snippet-line-44')).toBeInTheDocument();
  });

  it('highlights only the lines within [lineStart, lineEnd]', () => {
    render(
      <SnippetViewer
        snippet={'a\nb\nc\nd'}
        startLine={10}
        lineStart={11}
        lineEnd={12}
      />,
    );

    expect(screen.getByTestId('snippet-line-10')).toHaveAttribute(
      'data-highlighted',
      'false',
    );
    expect(screen.getByTestId('snippet-line-11')).toHaveAttribute(
      'data-highlighted',
      'true',
    );
    expect(screen.getByTestId('snippet-line-12')).toHaveAttribute(
      'data-highlighted',
      'true',
    );
    expect(screen.getByTestId('snippet-line-13')).toHaveAttribute(
      'data-highlighted',
      'false',
    );
  });

  it('falls back to lineStart when startLine is null', () => {
    render(
      <SnippetViewer
        snippet={'first\nsecond'}
        startLine={null}
        lineStart={7}
        lineEnd={7}
      />,
    );

    expect(screen.getByTestId('snippet-line-7')).toHaveAttribute(
      'data-highlighted',
      'true',
    );
    expect(screen.getByTestId('snippet-line-8')).toBeInTheDocument();
  });

  it('falls back to line 1 when both line numbers are null', () => {
    render(
      <SnippetViewer
        snippet={'only line'}
        startLine={null}
        lineStart={null}
        lineEnd={null}
      />,
    );

    expect(screen.getByTestId('snippet-line-1')).toBeInTheDocument();
  });
});
