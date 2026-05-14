/**
 * Filename → CodeMirror language extension picker.
 *
 * Why a tiny static map (and not a full grammar bundle)?
 * - Each language pack is ~30–80 KB minified.
 * - We only need the languages the scanner actually targets day-one.
 * - Dynamic importing the pack here would defer the parse cost until
 *   the editor mounts, but the editor mounts immediately on this route
 *   so there's no win — just bundle them as siblings of the lazy editor.
 *
 * Returns the matched extension or `null` for plain text. Callers should
 * pass the result straight into the CodeMirror `extensions` array — when
 * `null`, no language extension is installed and the editor renders as
 * a no-highlight pre-formatted block.
 */
import { javascript } from '@codemirror/lang-javascript';
import { json } from '@codemirror/lang-json';
import { python } from '@codemirror/lang-python';
import type { Extension } from '@codemirror/state';

type LanguageFactory = () => Extension;

/**
 * Extension → factory map. We choose factories over pre-instantiated
 * extensions because some packs (like `lang-javascript`) accept options
 * (jsx, typescript) and we want to pass them per file.
 */
const EXTENSION_TO_FACTORY: Record<string, LanguageFactory> = {
  cjs: () => javascript({ jsx: false, typescript: false }),
  js: () => javascript({ jsx: false, typescript: false }),
  json: () => json(),
  jsx: () => javascript({ jsx: true, typescript: false }),
  mjs: () => javascript({ jsx: false, typescript: false }),
  py: () => python(),
  pyi: () => python(),
  ts: () => javascript({ jsx: false, typescript: true }),
  tsx: () => javascript({ jsx: true, typescript: true }),
};

export function pickLanguage(filename: string): Extension | null {
  // Match on the trailing token after the last dot. Files without an
  // extension (`Dockerfile`, `Makefile`) fall back to plain text — the
  // viewer is still useful, just without highlighting.
  const dot = filename.lastIndexOf('.');
  if (dot === -1 || dot === filename.length - 1) return null;
  const ext = filename.slice(dot + 1).toLowerCase();
  const factory = EXTENSION_TO_FACTORY[ext];
  return factory ? factory() : null;
}
