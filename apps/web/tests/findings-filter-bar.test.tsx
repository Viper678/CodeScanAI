import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { FindingsFilterBar } from '@/components/findings/findings-filter-bar';

describe('<FindingsFilterBar />', () => {
  it('marks active severity / scan-type chips via aria-pressed', () => {
    render(
      <FindingsFilterBar
        filters={{
          file_id: null,
          scan_type: ['security'],
          severity: ['high'],
        }}
        onClear={vi.fn()}
        onToggleScanType={vi.fn()}
        onToggleSeverity={vi.fn()}
      />,
    );

    expect(screen.getByTestId('filter-severity-high')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByTestId('filter-severity-low')).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(screen.getByTestId('filter-scan-type-security')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByTestId('filter-scan-type-bugs')).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('invokes the right callback when chips are clicked', () => {
    const onToggleSeverity = vi.fn();
    const onToggleScanType = vi.fn();

    render(
      <FindingsFilterBar
        filters={{
          file_id: null,
          scan_type: [],
          severity: [],
        }}
        onClear={vi.fn()}
        onToggleScanType={onToggleScanType}
        onToggleSeverity={onToggleSeverity}
      />,
    );

    fireEvent.click(screen.getByTestId('filter-severity-critical'));
    expect(onToggleSeverity).toHaveBeenCalledWith('critical');

    fireEvent.click(screen.getByTestId('filter-scan-type-keywords'));
    expect(onToggleScanType).toHaveBeenCalledWith('keywords');
  });

  it('hides the Clear button when no filters are active', () => {
    render(
      <FindingsFilterBar
        filters={{
          file_id: null,
          scan_type: [],
          severity: [],
        }}
        onClear={vi.fn()}
        onToggleScanType={vi.fn()}
        onToggleSeverity={vi.fn()}
      />,
    );

    expect(screen.queryByTestId('filter-clear')).not.toBeInTheDocument();
  });

  it('shows the Clear button + file chip when file_id is set', () => {
    const onClear = vi.fn();
    render(
      <FindingsFilterBar
        filters={{
          file_id: 'file-9',
          scan_type: [],
          severity: [],
        }}
        onClear={onClear}
        onToggleScanType={vi.fn()}
        onToggleSeverity={vi.fn()}
      />,
    );

    expect(screen.getByTestId('filter-file-active')).toHaveTextContent(
      'file: file-9',
    );

    fireEvent.click(screen.getByTestId('filter-clear'));
    expect(onClear).toHaveBeenCalledTimes(1);
  });
});
