import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Heavy-mock CodeMirror so this test runs in jsdom without pulling in the
// real editor runtime. We assert on the props the wrapper passes through —
// that's the surface the rest of the app relies on. The actual editor
// behavior is exercised at runtime; covering it in a unit test would
// require a browser environment we don't ship.
const cmCalls: Array<Record<string, unknown>> = [];

vi.mock('@uiw/react-codemirror', () => {
  const fakeView = {};
  function CodeMirror(props: Record<string, unknown>) {
    cmCalls.push(props);
    // Mimic onCreateEditor synchronously so the wrapper's ref is set.
    const onCreateEditor = props.onCreateEditor as
      | ((view: typeof fakeView) => void)
      | undefined;
    onCreateEditor?.(fakeView);
    return (
      <div
        data-testid="cm-mock"
        data-extension-count={
          Array.isArray(props.extensions) ? props.extensions.length : 0
        }
      >
        {String(props.value)}
      </div>
    );
  }
  return {
    __esModule: true,
    default: CodeMirror,
    EditorView: {
      theme: () => ({}),
      editable: { of: () => ({}) },
      lineWrapping: {},
      scrollIntoView: () => ({}),
    },
  };
});

vi.mock('@codemirror/theme-one-dark', () => ({ oneDark: {} }));

vi.mock('next-themes', () => ({
  useTheme: () => ({ resolvedTheme: 'dark' }),
}));

import { CodeEditor } from '@/components/file-viewer/code-editor';

describe('<CodeEditor />', () => {
  it('renders the supplied content via the CodeMirror wrapper', () => {
    cmCalls.length = 0;
    render(
      <CodeEditor
        content="print('hi')"
        filename="hello.py"
        markers={[]}
        onMarkerClick={vi.fn()}
        scrollToLine={null}
      />,
    );
    expect(screen.getByTestId('cm-mock')).toHaveTextContent("print('hi')");
    // The wrapper installs at minimum: editable, lineWrapping, theme, gutter
    // = 4 extensions; +1 when a language pack matches.
    const node = screen.getByTestId('cm-mock');
    const count = Number.parseInt(node.dataset.extensionCount ?? '0', 10);
    expect(count).toBeGreaterThanOrEqual(4);
  });

  it('passes a python language extension for .py files (extension count grows)', () => {
    cmCalls.length = 0;
    render(
      <CodeEditor
        content="x = 1"
        filename="src/foo.py"
        markers={[]}
        onMarkerClick={vi.fn()}
        scrollToLine={null}
      />,
    );
    const pyCount = Number.parseInt(
      screen.getByTestId('cm-mock').dataset.extensionCount ?? '0',
      10,
    );
    cmCalls.length = 0;
    render(
      <CodeEditor
        content="x = 1"
        filename="src/foo.unknownext"
        markers={[]}
        onMarkerClick={vi.fn()}
        scrollToLine={null}
      />,
    );
    const noLangCount = Number.parseInt(
      screen.getAllByTestId('cm-mock')[1]?.dataset.extensionCount ?? '0',
      10,
    );
    expect(pyCount).toBe(noLangCount + 1);
  });
});
