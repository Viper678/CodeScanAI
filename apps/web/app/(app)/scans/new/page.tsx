import { redirect } from 'next/navigation';

/**
 * `/scans/new` is a legacy entry point left over from the wizard scaffolding.
 * The canonical wizard URL is `/uploads/new` (since the flow starts with an
 * upload). Redirect server-side so existing links / bookmarks continue to
 * work and the surface stays singular.
 */
export default function LegacyNewScanRedirect() {
  redirect('/uploads/new');
}
