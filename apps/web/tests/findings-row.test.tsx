import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { FindingsRow } from '@/components/findings/findings-row';
import type { Finding } from '@/lib/api/findings/types';

function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    confidence: 0.9,
    file: { id: 'file-1', path: 'src/api/users.py' },
    id: 'f-1',
    line_end: 44,
    line_start: 42,
    message: 'String concatenation in SQL allows injection.',
    recommendation: 'Use parameterized queries.',
    rule_id: 'CWE-89',
    scan_type: 'security',
    severity: 'high',
    snippet: 'def get(id):\n  q = "SELECT * FROM u WHERE id=" + id\n  return q',
    title: 'SQL injection via string concatenation',
    ...overrides,
  };
}

function Harness({
  finding,
  fileHref = '/uploads/u-1/files/file-1',
}: Readonly<{ finding: Finding; fileHref?: string }>) {
  const [expanded, setExpanded] = useState(false);
  return (
    <FindingsRow
      finding={finding}
      expanded={expanded}
      onToggle={() => setExpanded((prev) => !prev)}
      fileHref={fileHref}
    />
  );
}

describe('<FindingsRow />', () => {
  it('renders core columns: file path, line range, scan type, title', () => {
    render(<Harness finding={makeFinding()} />);

    expect(screen.getByText('src/api/users.py')).toBeInTheDocument();
    expect(screen.getByText('42–44')).toBeInTheDocument();
    expect(screen.getByText('Security')).toBeInTheDocument();
    expect(
      screen.getByText('SQL injection via string concatenation'),
    ).toBeInTheDocument();
  });

  it('shows a single line number when start == end', () => {
    render(<Harness finding={makeFinding({ line_end: 42, line_start: 42 })} />);
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('renders an em-dash for the line column when line_start is null', () => {
    render(
      <Harness finding={makeFinding({ line_end: null, line_start: null })} />,
    );
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('expands and collapses on Enter and Space (keyboard accessible)', () => {
    render(<Harness finding={makeFinding()} />);

    const row = screen.getByRole('button', { expanded: false });
    expect(screen.queryByTestId('finding-details-f-1')).not.toBeInTheDocument();

    fireEvent.keyDown(row, { code: 'Enter', key: 'Enter' });
    expect(screen.getByTestId('finding-details-f-1')).toBeInTheDocument();
    expect(row).toHaveAttribute('aria-expanded', 'true');

    fireEvent.keyDown(row, { code: 'Space', key: ' ' });
    expect(screen.queryByTestId('finding-details-f-1')).not.toBeInTheDocument();
    expect(row).toHaveAttribute('aria-expanded', 'false');
  });

  it('renders message + recommendation + snippet when expanded', () => {
    render(<Harness finding={makeFinding()} />);
    fireEvent.click(screen.getByRole('button'));

    expect(
      screen.getByText('String concatenation in SQL allows injection.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Use parameterized queries.')).toBeInTheDocument();
    expect(screen.getByTestId('snippet-viewer')).toBeInTheDocument();
    expect(screen.getByText('CWE-89')).toBeInTheDocument();
    expect(screen.getByText('90%')).toBeInTheDocument();
  });

  it('omits recommendation block when null', () => {
    render(<Harness finding={makeFinding({ recommendation: null })} />);
    fireEvent.click(screen.getByRole('button'));

    expect(screen.queryByText('Recommendation')).not.toBeInTheDocument();
  });

  it('clicking the file link does not toggle the row', () => {
    const onToggle = vi.fn();
    render(
      <FindingsRow
        finding={makeFinding()}
        expanded={false}
        onToggle={onToggle}
        fileHref="/uploads/u-1/files/file-1"
      />,
    );

    const link = screen.getByRole('link', { name: 'src/api/users.py' });
    expect(link).toHaveAttribute('href', '/uploads/u-1/files/file-1');
    fireEvent.click(link);
    expect(onToggle).not.toHaveBeenCalled();
  });
});
