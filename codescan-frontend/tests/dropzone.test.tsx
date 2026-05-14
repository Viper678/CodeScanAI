import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Dropzone } from '@/components/upload/dropzone';

describe('<Dropzone />', () => {
  it('renders the upload-limit hint copy', () => {
    render(<Dropzone onFileSelected={() => undefined} />);
    expect(screen.getByText(/100 MB per archive/i)).toBeInTheDocument();
  });

  it('marks itself disabled when the disabled prop is set', () => {
    render(<Dropzone disabled onFileSelected={() => undefined} />);

    const zone = screen.getByTestId('upload-dropzone');
    expect(zone).toHaveAttribute('data-disabled', 'true');

    const input = zone.querySelector('input[type="file"]');
    expect(input).toBeDisabled();
  });

  it('invokes onFileSelected when the user picks a file via the hidden input', () => {
    const onFileSelected = vi.fn();
    render(<Dropzone onFileSelected={onFileSelected} />);

    const file = new File(['hello'], 'repo.zip', { type: 'application/zip' });
    const input = screen
      .getByTestId('upload-dropzone')
      .querySelector('input[type="file"]') as HTMLInputElement;

    // userEvent.upload pulls in extra deps; fireEvent on a real input works.
    Object.defineProperty(input, 'files', { value: [file] });
    input.dispatchEvent(new Event('change', { bubbles: true }));

    expect(onFileSelected).toHaveBeenCalledTimes(1);
    expect(onFileSelected.mock.calls[0]?.[0]).toBe(file);
  });
});
