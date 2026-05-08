import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ProgressHeader } from '@/components/scan-progress/progress-header';
import type { ScanDetail, ScanStatus } from '@/lib/api/scans/types';

function makeScan(status: ScanStatus, overrides: Partial<ScanDetail> = {}) {
  return {
    created_at: '2026-05-01T12:00:00Z',
    error: null,
    finished_at: null,
    id: 'scan-1',
    name: 'Demo scan',
    progress_done: 12,
    progress_total: 50,
    scan_types: ['security'],
    started_at: '2026-05-01T12:00:00Z',
    status,
    summary: { by_severity: {}, by_type: {} },
    upload_id: 'u-1',
    ...overrides,
  } satisfies ScanDetail;
}

function renderWith(
  status: ScanStatus,
  props: Partial<{ cancelling: boolean }> = {},
) {
  const onCancel = vi.fn();
  render(
    <ProgressHeader
      scan={makeScan(status)}
      cancelling={props.cancelling ?? false}
      onCancel={onCancel}
    />,
  );
  return { onCancel };
}

describe('<ProgressHeader />', () => {
  it('shows Cancel while running', () => {
    renderWith('running');
    expect(screen.getByTestId('scan-cancel')).toBeInTheDocument();
  });

  it('shows Cancel while pending', () => {
    renderWith('pending');
    expect(screen.getByTestId('scan-cancel')).toBeInTheDocument();
  });

  it.each<ScanStatus>(['completed', 'failed', 'cancelled'])(
    'shows no controls in terminal state (%s)',
    (status) => {
      renderWith(status);
      expect(screen.queryByTestId('scan-cancel')).not.toBeInTheDocument();
    },
  );

  it('fires onCancel on click', () => {
    const { onCancel } = renderWith('running');
    fireEvent.click(screen.getByTestId('scan-cancel'));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('disables Cancel while the cancel mutation is pending', () => {
    renderWith('running', { cancelling: true });
    expect(screen.getByTestId('scan-cancel')).toBeDisabled();
  });
});
