import Link from "next/link";
import Image from "next/image";
import { createClient } from "@/lib/supabase-server";
import { Nav } from "@/components/nav";
import { WatchButton } from "@/components/watch-button";
import { clp, km as fmtKm, daysSince } from "@/lib/format";
import type { Listing } from "@/lib/types";

export const dynamic = "force-dynamic";

async function load() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { watches: [], listings: [] };

  const { data: watches } = await supabase
    .from("watchlist")
    .select("listing_id, added_at, notes")
    .eq("user_id", user.id)
    .order("added_at", { ascending: false });

  const ids = (watches ?? []).map((w) => w.listing_id);
  if (ids.length === 0) return { watches: watches ?? [], listings: [] };

  const { data: listings } = await supabase
    .from("listings")
    .select(
      "id, source, url, title, make, model, version, year, km, fuel_type, region, latest_price_clp, first_seen_at, removed_at, image_url",
    )
    .in("id", ids);

  return { watches: watches ?? [], listings: (listings ?? []) as Partial<Listing>[] };
}

export default async function Page() {
  const { watches, listings } = await load();
  const byId = new Map<number, Partial<Listing>>();
  for (const l of listings) if (l.id != null) byId.set(l.id as number, l);

  return (
    <div>
      <Nav pathname="/watchlist" />
      <main className="mx-auto max-w-7xl space-y-5 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">Watchlist</h1>
          <p className="mt-1 text-sm text-neutral-400">
            {watches.length === 0
              ? "No listings saved. Tap the ⭐ on any listing to save it here."
              : `${watches.length} listing${watches.length === 1 ? "" : "s"} saved.`}
          </p>
        </header>

        {watches.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-neutral-800">
            <table className="min-w-full divide-y divide-neutral-800 text-sm">
              <thead className="bg-neutral-900 text-xs uppercase tracking-wider text-neutral-400">
                <tr>
                  <th className="px-3 py-2 text-left w-10"></th>
                  <th className="px-3 py-2 text-left">Photo</th>
                  <th className="px-3 py-2 text-left">Title</th>
                  <th className="px-3 py-2 text-right">Year</th>
                  <th className="px-3 py-2 text-right">Km</th>
                  <th className="px-3 py-2 text-right">Price</th>
                  <th className="px-3 py-2 text-left">Source</th>
                  <th className="px-3 py-2 text-right">Saved</th>
                  <th className="px-3 py-2 text-left">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-900 bg-neutral-950">
                {watches.map((w) => {
                  const r = byId.get(w.listing_id);
                  if (!r) {
                    return (
                      <tr key={w.listing_id}>
                        <td colSpan={9} className="px-3 py-2 text-neutral-500">
                          Listing {w.listing_id} no longer available
                        </td>
                      </tr>
                    );
                  }
                  const removed = !!r.removed_at;
                  return (
                    <tr key={r.id} className="hover:bg-neutral-900/60">
                      <td className="px-3 py-2">
                        <WatchButton
                          listingId={r.id as number}
                          initial={true}
                          variant="icon"
                        />
                      </td>
                      <td className="px-3 py-2">
                        {r.image_url ? (
                          <Image
                            src={r.image_url}
                            alt=""
                            width={72}
                            height={48}
                            className="h-12 w-18 rounded object-cover"
                            unoptimized
                          />
                        ) : (
                          <div className="h-12 w-18 rounded bg-neutral-800" />
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <Link
                          href={`/listings/${r.id}`}
                          className="font-medium hover:underline"
                        >
                          {r.title ?? `${r.make ?? ""} ${r.model ?? ""}`.trim() ?? "—"}
                        </Link>
                        <div className="text-xs text-neutral-500">
                          {r.make} {r.model} {r.version ?? ""} · {r.region ?? "?"}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.year ?? "—"}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{fmtKm(r.km)}</td>
                      <td className="px-3 py-2 text-right tabular-nums font-medium">
                        {clp(r.latest_price_clp)}
                      </td>
                      <td className="px-3 py-2 text-neutral-400">{r.source}</td>
                      <td className="px-3 py-2 text-right text-neutral-500 tabular-nums">
                        {daysSince(w.added_at) ?? 0}d
                      </td>
                      <td className="px-3 py-2">
                        {removed ? (
                          <span className="rounded bg-red-950/40 px-2 py-0.5 text-xs text-red-300">
                            removed
                          </span>
                        ) : (
                          <span className="rounded bg-emerald-950/40 px-2 py-0.5 text-xs text-emerald-300">
                            active
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
