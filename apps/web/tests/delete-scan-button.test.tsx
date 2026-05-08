import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DeleteScanButton } from '@/components/scans/delete-scan-button';
import { ApiError } from '@/lib/api/auth/errors';

const { useDeleteScanMutationMock } = vi.hoisted(() => ({
  useDeleteScanMutationMock: vi.fn(),
}));

vi.mock('@/lib/api/scans/use-scans', () => ({
  useDeleteScanMutation: () => useDeleteScanMutationMock(),
}));

type MutateArg = (
  scanId: string,
  opts?: {
    onSuccess?: () => void;
    onError?: (err: ApiError) => void;
  },
) => void;

function setUpMutation(impl?: { isPending?: boolean; mutate?: MutateArg }) {
  useDeleteScanMutationMock.mockReturnValue({
    isPending: impl?.isPending ?? false,
    mutate: impl?.mutate ?? vi.fn(),
  });
}

describe('<DeleteScanButton />', () => {
  beforeEach(() => {
    useDeleteScanMutationMock.mockReset();
  });

  it('does not call the mutation until the user opens the dialog and confirms', async () => {
    const mutate = vi.fn();
    setUpMutation({ mutate });

    render(<DeleteScanButton scanId="s-1" scanName="My scan" />);

    // Initially closed — no destructive button visible yet.
    expect(
      screen.queryByTestId('scan-row-s-1-delete-confirm'),
    ).not.toBeInTheDocument();
    expect(mutate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('scan-row-s-1-delete'));

    // Dialog opens — confirm button appears.
    const confirm = await screen.findByTestId('scan-row-s-1-delete-confirm');
    fireEvent.click(confirm);

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0]![0]).toBe('s-1');
  });

  it('does NOT call the mutation when the user clicks Cancel', async () => {
    const mutate = vi.fn();
    setUpMutation({ mutate });

    render(<DeleteScanButton scanId="s-1" scanName="My scan" />);

    fireEvent.click(screen.getByTestId('scan-row-s-1-delete'));
    fireEvent.click(await screen.findByTestId('scan-row-s-1-delete-cancel'));

    expect(mutate).not.toHaveBeenCalled();
  });

  it('renders the destructive copy in the dialog body', async () => {
    setUpMutation();
    render(<DeleteScanButton scanId="s-1" scanName="My scan" />);

    fireEvent.click(screen.getByTestId('scan-row-s-1-delete'));

    expect(
      await screen.findByText(/delete scan permanently/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/findings for this scan will be removed/i),
    ).toBeInTheDocument();
  });

  it('surfaces the API error message when the mutation rejects', async () => {
    const mutate = vi.fn(
      (
        _scanId: string,
        opts?: {
          onSuccess?: () => void;
          onError?: (err: ApiError) => void;
        },
      ) => {
        opts?.onError?.(
          new ApiError(500, 'server_error', 'Boom from the server.'),
        );
      },
    );
    setUpMutation({ mutate });

    render(<DeleteScanButton scanId="s-1" scanName="My scan" />);

    fireEvent.click(screen.getByTestId('scan-row-s-1-delete'));
    fireEvent.click(await screen.findByTestId('scan-row-s-1-delete-confirm'));

    await waitFor(() => {
      expect(screen.getByTestId('scan-row-s-1-delete-error')).toHaveTextContent(
        'Boom from the server.',
      );
    });
  });
});
