import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ScansFilterBar } from '@/components/scans/scans-filter-bar';

describe('<ScansFilterBar />', () => {
  it('marks active status chips via aria-pressed', () => {
    render(
      <ScansFilterBar
        filters={{ status: ['running', 'failed'] }}
        onClear={vi.fn()}
        onToggleStatus={vi.fn()}
      />,
    );

    expect(screen.getByTestId('filter-status-running')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByTestId('filter-status-failed')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByTestId('filter-status-completed')).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('invokes onToggleStatus with the chip id when clicked', () => {
    const onToggleStatus = vi.fn();
    render(
      <ScansFilterBar
        filters={{ status: [] }}
        onClear={vi.fn()}
        onToggleStatus={onToggleStatus}
      />,
    );

    fireEvent.click(screen.getByTestId('filter-status-completed'));
    expect(onToggleStatus).toHaveBeenCalledWith('completed');

    fireEvent.click(screen.getByTestId('filter-status-cancelled'));
    expect(onToggleStatus).toHaveBeenCalledWith('cancelled');
  });

  it('hides Clear when no filters are active', () => {
    render(
      <ScansFilterBar
        filters={{ status: [] }}
        onClear={vi.fn()}
        onToggleStatus={vi.fn()}
      />,
    );

    expect(screen.queryByTestId('filter-clear')).not.toBeInTheDocument();
  });

  it('shows Clear and calls onClear when any filter is active', () => {
    const onClear = vi.fn();
    render(
      <ScansFilterBar
        filters={{ status: ['pending'] }}
        onClear={onClear}
        onToggleStatus={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId('filter-clear'));
    expect(onClear).toHaveBeenCalledTimes(1);
  });
});
