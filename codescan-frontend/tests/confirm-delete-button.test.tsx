import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ConfirmDeleteButton } from '@/components/confirm-delete-button';

describe('<ConfirmDeleteButton />', () => {
  it('shows a single trash trigger in the idle state', () => {
    render(
      <ConfirmDeleteButton
        label="upload"
        onConfirm={vi.fn().mockResolvedValue(undefined)}
        testId="del"
      />,
    );

    const trigger = screen.getByTestId('del-trigger');
    expect(trigger).toHaveAttribute('aria-label', 'Delete upload');
    // Confirm + cancel should not exist yet.
    expect(screen.queryByTestId('del-confirm')).toBeNull();
    expect(screen.queryByTestId('del-cancel')).toBeNull();
  });

  it('reveals confirm and cancel after the trigger is clicked', () => {
    render(
      <ConfirmDeleteButton
        label="scan"
        onConfirm={vi.fn().mockResolvedValue(undefined)}
        testId="del"
      />,
    );

    fireEvent.click(screen.getByTestId('del-trigger'));

    expect(screen.getByTestId('del-confirm')).toBeInTheDocument();
    expect(screen.getByTestId('del-cancel')).toBeInTheDocument();
    expect(screen.queryByTestId('del-trigger')).toBeNull();
  });

  it('calls onConfirm exactly once when the user confirms', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(
      <ConfirmDeleteButton label="scan" onConfirm={onConfirm} testId="del" />,
    );

    fireEvent.click(screen.getByTestId('del-trigger'));
    fireEvent.click(screen.getByTestId('del-confirm'));

    await waitFor(() => {
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });
  });

  it('returns to idle when Cancel is clicked without firing onConfirm', () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDeleteButton label="scan" onConfirm={onConfirm} testId="del" />,
    );

    fireEvent.click(screen.getByTestId('del-trigger'));
    fireEvent.click(screen.getByTestId('del-cancel'));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByTestId('del-trigger')).toBeInTheDocument();
    expect(screen.queryByTestId('del-confirm')).toBeNull();
  });

  it('returns to idle and forwards errors when onConfirm rejects', async () => {
    const error = new Error('server hates you');
    const onConfirm = vi.fn().mockRejectedValue(error);
    const onError = vi.fn();
    render(
      <ConfirmDeleteButton
        label="scan"
        onConfirm={onConfirm}
        onError={onError}
        testId="del"
      />,
    );

    fireEvent.click(screen.getByTestId('del-trigger'));
    fireEvent.click(screen.getByTestId('del-confirm'));

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith(error);
    });
    // After the rejection we should be back in idle so the user can retry.
    await waitFor(() => {
      expect(screen.getByTestId('del-trigger')).toBeInTheDocument();
    });
  });

  it('stops click propagation so a row-level link is not followed', () => {
    const rowClick = vi.fn();
    render(
      // Wrap in a clickable parent to mimic a row anchor; the trigger should
      // not bubble its click up.
      <div onClick={rowClick}>
        <ConfirmDeleteButton
          label="scan"
          onConfirm={vi.fn().mockResolvedValue(undefined)}
          testId="del"
        />
      </div>,
    );

    fireEvent.click(screen.getByTestId('del-trigger'));
    fireEvent.click(screen.getByTestId('del-cancel'));

    // The parent div must not have observed the click — otherwise the row's
    // navigation would race the confirmation flow.
    expect(rowClick).not.toHaveBeenCalled();
  });

  it('disables interaction when `disabled` is true', () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDeleteButton
        label="scan"
        onConfirm={onConfirm}
        disabled
        testId="del"
      />,
    );

    const trigger = screen.getByTestId('del-trigger');
    fireEvent.click(trigger);
    expect(screen.queryByTestId('del-confirm')).toBeNull();
  });
});
