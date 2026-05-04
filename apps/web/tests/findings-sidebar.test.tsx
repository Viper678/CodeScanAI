import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { FindingsSidebar } from '@/components/file-viewer/findings-sidebar';
import type { Finding } from '@/lib/api/findings/types';

function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    confidence: 0.9,
    file: { id: 'file-1', path: 'src/api/users.py' },
    id: 'f-1',
    line_end: 12,
    line_start: 10,
    message: 'msg',
    recommendation: null,
    rule_id: null,
    scan_type: 'security',
    severity: 'high',
    snippet: null,
    title: 'SQL injection',
    ...overrides,
  };
}

describe('<FindingsSidebar />', () => {
  it('renders nothing actionable when there is no scan context', () => {
    render(
      <FindingsSidebar
        findings={[]}
        selectedId={null}
        onSelect={vi.fn()}
        isLoading={false}
        hasScanContext={false}
      />,
    );
    expect(
      screen.getByText(
        'Open a file from a scan results page to see its findings here.',
      ),
    ).toBeInTheDocument();
  });

  it('shows a loading state while findings are pending', () => {
    render(
      <FindingsSidebar
        findings={[]}
        selectedId={null}
        onSelect={vi.fn()}
        isLoading={true}
        hasScanContext={true}
      />,
    );
    expect(screen.getByText('Loading findings…')).toBeInTheDocument();
  });

  it('lists findings with title, scan type label, and line', () => {
    render(
      <FindingsSidebar
        findings={[
          makeFinding({ id: 'f-a', line_start: 10, title: 'A' }),
          makeFinding({
            id: 'f-b',
            line_start: 22,
            scan_type: 'bugs',
            title: 'B',
          }),
        ]}
        selectedId={null}
        onSelect={vi.fn()}
        isLoading={false}
        hasScanContext={true}
      />,
    );
    expect(screen.getByText('Findings (2)')).toBeInTheDocument();
    expect(screen.getByText('A')).toBeInTheDocument();
    expect(screen.getByText('B')).toBeInTheDocument();
    expect(screen.getByText('Security · line 10')).toBeInTheDocument();
    expect(screen.getByText('Bugs · line 22')).toBeInTheDocument();
  });

  it('renders the empty state when there are no findings on this file', () => {
    render(
      <FindingsSidebar
        findings={[]}
        selectedId={null}
        onSelect={vi.fn()}
        isLoading={false}
        hasScanContext={true}
      />,
    );
    expect(screen.getByText('No findings on this file.')).toBeInTheDocument();
  });

  it('marks the selected item active and invokes onSelect on click', () => {
    const onSelect = vi.fn();
    const findings = [
      makeFinding({ id: 'f-a', line_start: 10, title: 'A' }),
      makeFinding({ id: 'f-b', line_start: 22, title: 'B' }),
    ];
    render(
      <FindingsSidebar
        findings={findings}
        selectedId="f-a"
        onSelect={onSelect}
        isLoading={false}
        hasScanContext={true}
      />,
    );
    expect(screen.getByTestId('sidebar-item-f-a')).toHaveAttribute(
      'data-active',
      'true',
    );
    expect(screen.getByTestId('sidebar-item-f-b')).toHaveAttribute(
      'data-active',
      'false',
    );

    fireEvent.click(screen.getByTestId('sidebar-item-f-b'));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0]?.[0]).toMatchObject({ id: 'f-b' });
  });

  it('renders an em-dash when line_start is null', () => {
    render(
      <FindingsSidebar
        findings={[makeFinding({ line_end: null, line_start: null })]}
        selectedId={null}
        onSelect={vi.fn()}
        isLoading={false}
        hasScanContext={true}
      />,
    );
    expect(screen.getByText('Security · line —')).toBeInTheDocument();
  });
});
