'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { AlertTriangle, ArrowLeft, FileWarning, Loader2 } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';

import { FindingsSidebar } from '@/components/file-viewer/findings-sidebar';
import type { FindingMarker } from '@/components/file-viewer/finding-gutter';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ApiError } from '@/lib/api/client';
import { useFileContent } from '@/lib/api/file-content/use-file-content';
import { useFindingsForFile } from '@/lib/api/findings/use-findings';
import type { Finding } from '@/lib/api/findings/types';

/**
 * Lazy-loaded CodeMirror editor. The runtime cost (~150–300 KB minified
 * once language packs land) is paid only when this route mounts — not
 * for users who never click a finding. ``ssr: false`` because CodeMirror
 * touches `window` during initialization.
 */
const CodeEditor = dynamic(
  () =>
    import('@/components/file-viewer/code-editor').then(
      (mod) => mod.CodeEditor,
    ),
  {
    loading: () => <EditorLoadingState />,
    ssr: false,
  },
);

type FileViewerPageProps = {
  uploadId: string;
  fileId: string;
  scanId: string | null;
  /** 1-indexed line to scroll to on mount. */
  initialLine: number | null;
};

/**
 * Top-level file viewer route content. Owns the cross-component state:
 * which finding is currently "selected" (drives the editor's scroll +
 * the sidebar's active row).
 *
 * Layout: header bar with the file path + back link, then a two-column
 * body — editor on the left (flex 1), sidebar on the right (fixed
 * width). On narrow viewports the sidebar drops below; we don't try to
 * make it especially fancy because file viewing on a phone is a niche
 * use case for v1.
 */
export function FileViewerPage({
  uploadId,
  fileId,
  scanId,
  initialLine,
}: Readonly<FileViewerPageProps>) {
  const contentQuery = useFileContent(uploadId, fileId);
  const findingsQuery = useFindingsForFile(scanId, fileId);
  // Memoize the items array so downstream useMemo / useCallback hooks
  // don't see a fresh `[]` reference on every render — that would
  // recompute markers and reseat the gutter click handler unnecessarily.
  const findings = useMemo<Finding[]>(
    () => findingsQuery.data?.items ?? [],
    [findingsQuery.data],
  );
  // Track the most-recently-clicked finding so the editor can scroll
  // imperatively each time the user picks a different one in the
  // sidebar — the URL `?line=` only seeds the *initial* position.
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  // Imperative scroll target: an object so re-selecting the same finding
  // still triggers the editor's effect. Setting `setImperativeScroll` to
  // `{ line: same, nonce: prev.nonce + 1 }` produces a fresh object identity
  // → React re-renders with new prop → editor's `useEffect` deps change →
  // scroll fires. A bare `setImperativeLine(line.line_start)` would be
  // Object.is-equal on repeat clicks and React would skip the update.
  const [imperativeScroll, setImperativeScroll] = useState<{
    line: number;
    nonce: number;
  } | null>(null);

  const markers = useMemo<FindingMarker[]>(
    () =>
      findings
        .filter(
          (f): f is Finding & { line_start: number } => f.line_start !== null,
        )
        .map((f) => ({
          id: f.id,
          line: f.line_start,
          severity: f.severity,
        })),
    [findings],
  );

  // Map gutter clicks back to the sidebar selection so visual state stays
  // in lockstep with the editor.
  const handleGutterClick = useCallback(
    (findingId: string) => {
      const match = findings.find((f) => f.id === findingId);
      if (!match) return;
      setSelectedFinding(match);
      // Don't re-trigger scroll — the click came from the gutter, the
      // line is already in view. Just update sidebar selection.
    },
    [findings],
  );

  const handleSidebarSelect = useCallback((finding: Finding) => {
    setSelectedFinding(finding);
    if (finding.line_start !== null) {
      const lineStart = finding.line_start;
      setImperativeScroll((prev) => ({
        line: lineStart,
        nonce: (prev?.nonce ?? 0) + 1,
      }));
    }
  }, []);

  // Initial mount uses the URL `?line=` value (nonce 0). After that, every
  // sidebar click bumps nonce → editor sees a new object identity → scrolls.
  const scrollTarget =
    imperativeScroll ??
    (initialLine !== null ? { line: initialLine, nonce: 0 } : null);

  // The header path: file_path comes from a finding row. If we have at
  // least one finding, prefer that; otherwise fall back to a UUID hint
  // (the path isn't known in the no-scan case until we add a dedicated
  // file-detail endpoint, which is out of scope for T4.3).
  const headerPath = findings[0]?.file.path ?? `file ${fileId.slice(0, 8)}…`;

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <ViewerHeader filename={headerPath} scanId={scanId} />
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="h-full min-h-0 overflow-hidden border-t border-border/60">
          <ViewerBody
            content={contentQuery.data}
            error={contentQuery.error}
            isLoading={contentQuery.isPending}
            filename={headerPath}
            markers={markers}
            scrollTarget={scrollTarget}
            onMarkerClick={handleGutterClick}
          />
        </div>
        <div className="h-full min-h-0 border-t border-border/60">
          <FindingsSidebar
            findings={findings}
            total={findingsQuery.data?.total ?? null}
            isLoading={findingsQuery.isPending && scanId !== null}
            hasScanContext={scanId !== null}
            selectedId={selectedFinding?.id ?? null}
            onSelect={handleSidebarSelect}
          />
        </div>
      </div>
    </div>
  );
}

type ViewerHeaderProps = {
  filename: string;
  scanId: string | null;
};

function ViewerHeader({ filename, scanId }: Readonly<ViewerHeaderProps>) {
  // "Back" goes to the originating scan results page when we have one,
  // otherwise to the user's scans list. We don't try to infer the
  // upload's tree page — a file viewer opened from /scans should return
  // there.
  const backHref = scanId ? `/scans/${scanId}` : '/scans';
  const backLabel = scanId ? 'Back to scan' : 'Back to scans';
  return (
    <header className="flex items-center gap-3 px-6 py-4">
      <Link
        href={backHref}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden="true" />
        {backLabel}
      </Link>
      <span
        data-testid="viewer-file-path"
        className="ml-2 truncate font-mono text-sm text-foreground"
        title={filename}
      >
        {filename}
      </span>
    </header>
  );
}

type ViewerBodyProps = {
  content: string | undefined;
  error: ApiError | null;
  isLoading: boolean;
  filename: string;
  markers: FindingMarker[];
  scrollTarget: { line: number; nonce: number } | null;
  onMarkerClick: (findingId: string) => void;
};

function ViewerBody({
  content,
  error,
  isLoading,
  filename,
  markers,
  scrollTarget,
  onMarkerClick,
}: Readonly<ViewerBodyProps>) {
  if (isLoading) {
    return <EditorLoadingState />;
  }
  if (error) {
    return <ErrorFallback error={error} />;
  }
  if (content === undefined) {
    // useQuery with no error and no data only happens when the query is
    // disabled; we always run it here, so this branch is defensive.
    return <EditorLoadingState />;
  }
  return (
    <CodeEditor
      content={content}
      filename={filename}
      markers={markers}
      onMarkerClick={onMarkerClick}
      scrollTarget={scrollTarget}
    />
  );
}

function EditorLoadingState() {
  return (
    <div
      data-testid="editor-loading"
      className="flex h-full items-center justify-center text-sm text-muted-foreground"
    >
      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
      <span className="ml-2">Loading file…</span>
    </div>
  );
}

function ErrorFallback({ error }: Readonly<{ error: ApiError }>) {
  // 413/415 are deterministic + user-actionable: explain why we can't
  // render. Everything else (404, 500, network) gets the generic panel.
  if (error.status === 413) {
    return (
      <FallbackCard
        icon={<FileWarning className="size-5 text-muted-foreground" />}
        title="File is too large to preview."
        body="This file exceeds the 2 MB preview limit. Larger files are out of scope for the in-app viewer in v1."
      />
    );
  }
  if (error.status === 415) {
    return (
      <FallbackCard
        icon={<FileWarning className="size-5 text-muted-foreground" />}
        title="Binary file — preview not supported."
        body="The viewer only renders text source files. Images, compiled artifacts, and other binary blobs would render as garbage."
      />
    );
  }
  if (error.status === 404) {
    return (
      <FallbackCard
        icon={<AlertTriangle className="size-5 text-muted-foreground" />}
        title="File not found."
        body="It may have been deleted or never extracted. If this scan is recent, try refreshing in a moment."
      />
    );
  }
  return (
    <FallbackCard
      icon={<AlertTriangle className="size-5 text-muted-foreground" />}
      title="Could not load this file."
      body={error.message}
    />
  );
}

type FallbackCardProps = {
  icon: React.ReactNode;
  title: string;
  body: string;
};

function FallbackCard({ icon, title, body }: Readonly<FallbackCardProps>) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <Card data-testid="viewer-fallback" className="max-w-md border-border/80">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base font-medium">
            {icon}
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{body}</p>
        </CardContent>
      </Card>
    </div>
  );
}
