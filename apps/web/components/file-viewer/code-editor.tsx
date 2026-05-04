'use client';

import CodeMirror, { EditorView } from '@uiw/react-codemirror';
import { oneDark } from '@codemirror/theme-one-dark';
import type { Extension } from '@codemirror/state';
import { useTheme } from 'next-themes';
import { useEffect, useMemo, useRef } from 'react';

import {
  findingGutter,
  type FindingMarker,
} from '@/components/file-viewer/finding-gutter';
import { pickLanguage } from '@/components/file-viewer/language';

type CodeEditorProps = {
  /** File text content to render. */
  content: string;
  /** Filename — used for language detection only. Not displayed here. */
  filename: string;
  /** Findings on this file, surfaced as gutter markers. */
  markers: FindingMarker[];
  /**
   * 1-indexed line to scroll into view on mount + whenever it changes.
   * `null` leaves the cursor at the top.
   */
  scrollToLine: number | null;
  /** Sidebar handshake: a clicked gutter dot fires this with the finding id. */
  onMarkerClick: (findingId: string) => void;
};

const READ_ONLY_THEME: Extension = EditorView.theme({
  '&': { fontSize: '13px', height: '100%' },
  '.cm-scroller': { fontFamily: 'var(--font-mono, ui-monospace, monospace)' },
  '.cm-content': { caretColor: 'transparent' },
  '.cs-line-flash': { backgroundColor: 'rgba(250, 204, 21, 0.18)' },
});

/**
 * Read-only CodeMirror 6 editor with finding-aware gutter markers.
 *
 * Why does this component own the imperative scroll/highlight (vs.
 * deriving it from props in the editor's `value`)? CodeMirror 6's
 * extension config is rebuilt only when its array reference changes —
 * which would unmount + re-mount the editor on every `scrollToLine`
 * change. We hold an `EditorView` ref and dispatch transactions instead.
 */
export function CodeEditor({
  content,
  filename,
  markers,
  scrollToLine,
  onMarkerClick,
}: Readonly<CodeEditorProps>) {
  const { resolvedTheme } = useTheme();
  const viewRef = useRef<EditorView | null>(null);

  // Recompute extensions when content/findings/theme change. The factory
  // pattern keeps the React reference stable for unrelated re-renders
  // (parent state changes, etc.) — useMemo is load-bearing here.
  const extensions = useMemo<Extension[]>(() => {
    const exts: Extension[] = [
      EditorView.editable.of(false),
      EditorView.lineWrapping,
      READ_ONLY_THEME,
      findingGutter(markers, onMarkerClick),
    ];
    const lang = pickLanguage(filename);
    if (lang) exts.push(lang);
    return exts;
  }, [filename, markers, onMarkerClick]);

  // Imperative scroll: dispatch a selection + scrollIntoView effect when
  // `scrollToLine` arrives. We resolve the line through doc.line so we
  // get the proper document offset; `scrollIntoView` with `y: "center"`
  // positions the line in the middle of the viewport (best UX for
  // jumping into the middle of a long file).
  useEffect(() => {
    if (scrollToLine === null) return;
    const view = viewRef.current;
    if (!view) return;
    const doc = view.state.doc;
    if (scrollToLine < 1 || scrollToLine > doc.lines) return;
    const line = doc.line(scrollToLine);
    view.dispatch({
      effects: EditorView.scrollIntoView(line.from, { y: 'center' }),
      selection: { anchor: line.from },
    });
    flashLine(view, line.from);
  }, [scrollToLine, content]);

  return (
    <div data-testid="code-editor" className="h-full overflow-hidden">
      <CodeMirror
        value={content}
        extensions={extensions}
        theme={resolvedTheme === 'dark' ? oneDark : 'light'}
        basicSetup={{
          // Defaults are fine; explicitly disable a few things that don't
          // make sense for read-only viewing (history, autocomplete, etc.)
          autocompletion: false,
          highlightActiveLine: false,
          highlightActiveLineGutter: true,
          history: false,
        }}
        onCreateEditor={(view) => {
          viewRef.current = view;
        }}
        height="100%"
        readOnly
        editable={false}
      />
    </div>
  );
}

/**
 * Briefly highlight a target line so the user can spot the jump
 * destination. Pure DOM work — CodeMirror exposes the line element
 * after layout, so we read it on the next animation frame.
 */
function flashLine(view: EditorView, pos: number): void {
  requestAnimationFrame(() => {
    const block = view.lineBlockAt(pos);
    if (!block) return;
    const dom = view.domAtPos(block.from);
    const node =
      dom.node.nodeType === 1
        ? (dom.node as HTMLElement)
        : (dom.node.parentElement as HTMLElement | null);
    if (!node) return;
    node.classList.add('cs-line-flash');
    window.setTimeout(() => node.classList.remove('cs-line-flash'), 1500);
  });
}
