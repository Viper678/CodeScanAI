import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DeleteUploadButton } from '@/components/upload/delete-upload-button';
import { ApiError } from '@/lib/api/auth/errors';

const { useDeleteUploadMutationMock } = vi.hoisted(() => ({
  useDeleteUploadMutationMock: vi.fn(),
}));

vi.mock('@/lib/api/uploads/use-upload', () => ({
  useDeleteUploadMutation: () => useDeleteUploadMutationMock(),
}));

type MutateArg = (
  uploadId: string,
  opts?: {
    onSuccess?: () => void;
    onError?: (err: ApiError) => void;
  },
) => void;

function setUpMutation(impl?: { isPending?: boolean; mutate?: MutateArg }) {
  useDeleteUploadMutationMock.mockReturnValue({
    isPending: impl?.isPending ?? false,
    mutate: impl?.mutate ?? vi.fn(),
  });
}

describe('<DeleteUploadButton />', () => {
  beforeEach(() => {
    useDeleteUploadMutationMock.mockReset();
  });

  it('confirm flow calls the mutation with the upload id', async () => {
    const mutate = vi.fn();
    setUpMutation({ mutate });

    render(<DeleteUploadButton uploadId="u-1" uploadName="repo.zip" />);

    fireEvent.click(screen.getByTestId('upload-row-u-1-delete'));
    fireEvent.click(await screen.findByTestId('upload-row-u-1-delete-confirm'));

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0]![0]).toBe('u-1');
  });

  it('cancel does NOT call the mutation', async () => {
    const mutate = vi.fn();
    setUpMutation({ mutate });

    render(<DeleteUploadButton uploadId="u-1" uploadName="repo.zip" />);

    fireEvent.click(screen.getByTestId('upload-row-u-1-delete'));
    fireEvent.click(await screen.findByTestId('upload-row-u-1-delete-cancel'));

    expect(mutate).not.toHaveBeenCalled();
  });

  it('warns about cascade — scans, findings, and disk extracts', async () => {
    setUpMutation();

    render(<DeleteUploadButton uploadId="u-1" uploadName="repo.zip" />);

    fireEvent.click(screen.getByTestId('upload-row-u-1-delete'));

    expect(
      await screen.findByText(/delete upload permanently/i),
    ).toBeInTheDocument();
    // Body must call out the cascade explicitly.
    const desc = screen.getByText(
      /associated scans and findings.*extracted files from disk/i,
    );
    expect(desc).toBeInTheDocument();
  });

  it('surfaces an inline error when the mutation rejects', async () => {
    const mutate = vi.fn(
      (
        _uploadId: string,
        opts?: {
          onSuccess?: () => void;
          onError?: (err: ApiError) => void;
        },
      ) => {
        opts?.onError?.(new ApiError(500, 'server_error', 'No bueno.'));
      },
    );
    setUpMutation({ mutate });

    render(<DeleteUploadButton uploadId="u-1" uploadName="repo.zip" />);

    fireEvent.click(screen.getByTestId('upload-row-u-1-delete'));
    fireEvent.click(await screen.findByTestId('upload-row-u-1-delete-confirm'));

    await waitFor(() => {
      expect(
        screen.getByTestId('upload-row-u-1-delete-error'),
      ).toHaveTextContent('No bueno.');
    });
  });
});
