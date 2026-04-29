import { NAV_ITEMS } from '@/lib/app-shell';

export default function Home() {
  return (
    <main className="min-h-screen bg-zinc-50 text-zinc-950">
      <header className="flex h-14 items-center border-b border-zinc-200 bg-white px-6">
        <h1 className="text-sm font-semibold">CodeScan</h1>
      </header>
      <div className="flex min-h-[calc(100vh-3.5rem)]">
        <aside className="w-56 border-r border-zinc-200 bg-white px-3 py-4">
          <nav aria-label="Primary navigation" className="space-y-1">
            {NAV_ITEMS.map((item) => (
              <div
                key={item}
                className="rounded px-3 py-2 text-sm font-medium text-zinc-700"
              >
                {item}
              </div>
            ))}
          </nav>
        </aside>
        <section aria-label="Page content" className="flex-1" />
      </div>
    </main>
  );
}
