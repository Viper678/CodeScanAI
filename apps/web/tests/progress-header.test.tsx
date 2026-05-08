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
  props: Partial<{
    cancelling: boolean;
    pausing: boolean;
    resuming: boolean;
  }> = {},
) {
  const onCancel = vi.fn();
  const onPause = vi.fn();
  const onResume = vi.fn();
  render(
    <ProgressHeader
      scan={makeScan(status)}
      cancelling={props.cancelling ?? false}
      pausing={props.pausing ?? false}
      resuming={props.resuming ?? false}
      onCancel={onCancel}
      onPause={onPause}
      onResume={onResume}
    />,
  );
  return { onCancel, onPause, onResume };
}

describe('<ProgressHeader />', () => {
  it('shows Pause + Cancel while running, no Resume', () => {
    renderWith('running');
    expect(screen.getByTestId('scan-pause')).toBeInTheDocument();
    expect(screen.getByTestId('scan-cancel')).toBeInTheDocument();
    expect(screen.queryByTestId('scan-resume')).not.toBeInTheDocument();
  });

  it('shows Resume + Cancel while paused, no Pause', () => {
    renderWith('paused');
    expect(screen.getByTestId('scan-resume')).toBeInTheDocument();
    expect(screen.getByTestId('scan-cancel')).toBeInTheDocument();
    expect(screen.queryByTestId('scan-pause')).not.toBeInTheDocument();
  });

  it('shows only Cancel while pending — pause is N/A before the worker starts', () => {
    renderWith('pending');
    expect(screen.getByTestId('scan-cancel')).toBeInTheDocument();
    expect(screen.queryByTestId('scan-pause')).not.toBeInTheDocument();
    expect(screen.queryByTestId('scan-resume')).not.toBeInTheDocument();
  });

  it.each<ScanStatus>(['completed', 'failed', 'cancelled'])(
    'shows no controls in terminal state (%s)',
    (status) => {
      renderWith(status);
      expect(screen.queryByTestId('scan-pause')).not.toBeInTheDocument();
      expect(screen.queryByTestId('scan-resume')).not.toBeInTheDocument();
      expect(screen.queryByTestId('scan-cancel')).not.toBeInTheDocument();
    },
  );

  it('fires the corresponding handler on click', () => {
    const { onPause } = renderWith('running');
    fireEvent.click(screen.getByTestId('scan-pause'));
    expect(onPause).toHaveBeenCalledTimes(1);
  });

  it('disables every visible control while any mutation is pending', () => {
    renderWith('paused', { resuming: true });
    expect(screen.getByTestId('scan-resume')).toBeDisabled();
    expect(screen.getByTestId('scan-cancel')).toBeDisabled();
  });
});
