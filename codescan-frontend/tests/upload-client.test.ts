import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/client';
import { uploadFile } from '@/lib/api/uploads/client';

type UploadHandler = ((event: ProgressEvent) => void) | null;

type FakeXhr = {
  status: number;
  responseText: string;
  withCredentials: boolean;
  upload: { onprogress: UploadHandler };
  open: ReturnType<typeof vi.fn>;
  send: ReturnType<typeof vi.fn>;
  abort: ReturnType<typeof vi.fn>;
  setRequestHeader: ReturnType<typeof vi.fn>;
  onload: (() => void) | null;
  onerror: (() => void) | null;
  onabort: (() => void) | null;
  __headers: Record<string, string>;
  __aborted: boolean;
};

type SendArg = FormData | string | null;

let lastXhr: FakeXhr | null = null;

function makeFakeXhr(): FakeXhr {
  const xhr = {
    __aborted: false,
    __headers: {} as Record<string, string>,
    onabort: null as (() => void) | null,
    onerror: null as (() => void) | null,
    onload: null as (() => void) | null,
    open: vi.fn(),
    responseText: '',
    send: vi.fn(),
    status: 0,
    upload: { onprogress: null as UploadHandler },
    withCredentials: false,
  };
  const abort = vi.fn(() => {
    xhr.__aborted = true;
    xhr.onabort?.();
  });
  const setRequestHeader = vi.fn((name: string, value: string) => {
    xhr.__headers[name] = value;
  });
  return Object.assign(xhr, { abort, setRequestHeader });
}

beforeEach(() => {
  lastXhr = null;
  // reason: we replace the global constructor with a stub for these tests
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).XMLHttpRequest = function FakeXMLHttpRequest() {
    const xhr = makeFakeXhr();
    lastXhr = xhr;
    return xhr;
  };
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('uploadFile', () => {
  it('sends a multipart POST with credentials and the CSRF header', async () => {
    const file = new File(['hello'], 'repo.zip', {
      type: 'application/zip',
    });

    const promise = uploadFile({ file, kind: 'zip' });

    // Simulate a successful response.
    const xhr = lastXhr!;
    xhr.status = 202;
    xhr.responseText = JSON.stringify({
      id: 'abc',
      kind: 'zip',
      original_name: 'repo.zip',
      size_bytes: 5,
      status: 'received',
    });
    xhr.onload?.();

    await expect(promise).resolves.toEqual({
      id: 'abc',
      kind: 'zip',
      original_name: 'repo.zip',
      size_bytes: 5,
      status: 'received',
    });

    expect(xhr.open).toHaveBeenCalledWith(
      'POST',
      expect.stringMatching(/\/uploads$/),
    );
    expect(xhr.withCredentials).toBe(true);
    expect(xhr.__headers['X-Requested-With']).toBe('codescan');
    // The browser must set Content-Type with the multipart boundary, so we
    // explicitly do NOT set it ourselves.
    expect(xhr.__headers['Content-Type']).toBeUndefined();

    const sent = (xhr.send.mock.calls[0]?.[0] ?? null) as SendArg;
    expect(sent).toBeInstanceOf(FormData);
    const form = sent as FormData;
    expect(form.get('kind')).toBe('zip');
    expect(form.get('file')).toBeInstanceOf(File);
  });

  it('reports progress fractions on lengthComputable events', async () => {
    const file = new File(['hello'], 'repo.zip');
    const onProgress = vi.fn();
    const promise = uploadFile({ file, kind: 'zip', onProgress });

    const xhr = lastXhr!;
    xhr.upload.onprogress?.({
      lengthComputable: true,
      loaded: 25,
      total: 100,
    } as ProgressEvent);
    xhr.upload.onprogress?.({
      lengthComputable: false,
      loaded: 0,
      total: 0,
    } as ProgressEvent);

    xhr.status = 202;
    xhr.responseText = JSON.stringify({
      id: 'x',
      kind: 'zip',
      original_name: 'repo.zip',
      size_bytes: 5,
      status: 'received',
    });
    xhr.onload?.();
    await promise;

    expect(onProgress).toHaveBeenNthCalledWith(1, 0.25);
    expect(onProgress).toHaveBeenNthCalledWith(2, null);
  });

  it('rejects with an ApiError carrying the envelope on non-2xx', async () => {
    const file = new File(['hello'], 'repo.zip');
    const promise = uploadFile({ file, kind: 'zip' });

    const xhr = lastXhr!;
    xhr.status = 413;
    xhr.responseText = JSON.stringify({
      error: {
        code: 'payload_too_large',
        message: 'Archive exceeds 100 MB.',
      },
    });
    xhr.onload?.();

    await expect(promise).rejects.toBeInstanceOf(ApiError);
    await promise.catch((err: unknown) => {
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(413);
      expect(apiErr.code).toBe('payload_too_large');
      expect(apiErr.message).toBe('Archive exceeds 100 MB.');
    });
  });

  it('rejects with an ApiError on network errors', async () => {
    const file = new File(['hello'], 'repo.zip');
    const promise = uploadFile({ file, kind: 'zip' });

    lastXhr!.onerror?.();

    await expect(promise).rejects.toBeInstanceOf(ApiError);
  });

  it('aborts the underlying XHR when the signal fires', async () => {
    const controller = new AbortController();
    const file = new File(['hello'], 'repo.zip');
    const promise = uploadFile({
      file,
      kind: 'zip',
      signal: controller.signal,
    });

    controller.abort();

    await expect(promise).rejects.toMatchObject({ name: 'AbortError' });
    expect(lastXhr!.abort).toHaveBeenCalled();
  });
});
