import Link from "next/link";
import Image from "next/image";
import { createClient } from "@/lib/supabase-server";
import { Nav } from "@/components/nav";
import { WatchButton } from "@/components/watch-button";
import { clp, km as fmtKm, daysSince, relTime } from "@/lib/format";

export const dynamic = "force-dynamic";

type PriceChange = {
  listing_id: number;
  first_price: number;
  latest_price: number;
  lowest_price: number;
  highest_price: number;
  first_observed: string;
  latest_observed: string;
  distinct_prices: number;
  observations: number;
  abs_change: number;
  pct_change: number;
  max_drop_abs: number;
  max_drop_pct: number;
};

type ListingLite = {
  id: number;
  source: string;
  url: string;
  title: string | null;
  make: string | null;
  model: string | null;
  version: string | null;
  year: number | null;
  km: number | null;
  region: string | null;
  image_url: string | null;
  latest_price_clp: number | null;
  first_seen_at: string;
  removed_at: string | null;
};

async function load(searchParams: { window?: string; min?: string }) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  const userId = user?.id ?? null;

  const windowDays = Math.max(1, Math.min(60, +(searchParams.window ?? "14")));
  const minDropPct = Math.max(0, Math.min(95, +(searchParams.min ?? "1")));
  const cutoff = new Date(Date.now() - windowDays * 86400 * 1000).toISOString();

  // Biggest drops within the window — pct_change is negative for drops.
  const { data: drops } = await supabase
    .from("price_changes")
    .select("*")
    .lt("pct_change", -minDropPct)
    .gte("latest_observed", cutoff)
    .order("pct_change", { ascending: true })
    .limit(100);

  const ids = (drops ?? []).map((d) => d.listing_id);
  if (ids.length === 0)
    return { items: [], windowDays, minDropPct, watchedIds: new Set<number>() };

  const { data: listings } = await supabase
    .from("listings")
    .select(
      "id,source,url,title,make,model,version,year,km,region,image_url,latest_price_clp,first_seen_at,removed_at",
    )
    .in("id", ids);

  const byId = new Map<number, ListingLite>();
  for (const l of (listings ?? []) as ListingLite[]) byId.set(l.id, l);

  const items = (drops as PriceChange[])
    .map((d) => ({ change: d, listing: byId.get(d.listing_id) }))
    .filter((x) => x.listing && !x.listing.removed_at);

  let watchedIds = new Set<number>();
  if (userId && ids.length) {
    const { data: w } = await supabase
      .from("watchlist")
      .select("listing_id")
      .eq("user_id", userId)
      .in("listing_id", ids);
    watchedIds = new Set((w ?? []).map((r: any) => r.listing_id));
  }

  return { items, windowDays, minDropPct, watchedIds };
}

export default async function Page({
  searchParams,
}: {
  searchParams: { window?: string; min?: string };
}) {
  const { items, windowDays, minDropPct, watchedIds } = await load(searchParams);

  return (
    <div>
      <Nav pathname="/price-drops" />
      <main className="mx-auto max-w-7xl space-y-5 px-6 py-8">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Price drops</h1>
            <p className="mt-1 text-sm text-neutral-400">
              Live listings whose price has fallen relative to what we first observed.
              Could be motivated-seller signal or pricing correction.
            </p>
          </div>
          <form
            method="GET"
            className="flex flex-wrap items-center gap-2 text-sm"
          >
            <label className="text-neutral-500">Window:</label>
            <select
              name="window"
              defaultValue={String(windowDays)}
              className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1"
            >
              <option value="3">3 days</option>
              <option value="7">7 days</option>
              <option value="14">14 days</option>
              <option value="30">30 days</option>
              <option value="60">60 days</option>
            </select>
            <label className="text-neutral-500">Min drop:</label>
            <select
              name="min"
              defaultValue={String(minDropPct)}
              className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1"
            >
              <option value="1">1%</option>
              <option value="3">3%</option>
              <option value="5">5%</option>
              <option value="10">10%</option>
              <option value="15">15%</option>
              <option value="20">20%</option>
            </select>
            <button className="rounded bg-white px-3 py-1 font-medium text-black hover:bg-neutral-200">
              Apply
            </button>
          </form>
        </header>

        <div className="text-sm text-neutral-400">
          {items.length} active listing{items.length === 1 ? "" : "s"} with ≥{minDropPct}% drop in last {windowDays}d
        </div>

        <div className="overflow-hidden rounded-lg border border-neutral-800">
          <table className="min-w-full divide-y divide-neutral-800 text-sm">
            <thead className="bg-neutral-900 text-xs uppercase tracking-wider text-neutral-400">
              <tr>
                <th className="px-3 py-2 text-left w-10"></th>
                <th className="px-3 py-2 text-left">Photo</th>
                <th className="px-3 py-2 text-left">Title</th>
                <th className="px-3 py-2 text-right">First $</th>
                <th className="px-3 py-2 text-right">Now $</th>
                <th className="px-3 py-2 text-right">Drop</th>
                <th className="px-3 py-2 text-right">Δ%</th>
                <th className="px-3 py-2 text-right">Obs</th>
                <th className="px-3 py-2 text-right">Days listed</th>
                <th className="px-3 py-2 text-left">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-900 bg-neutral-950">
              {items.map(({ change, listing }) => {
                if (!listing) return null;
                const age = daysSince(listing.first_seen_at);
                return (
                  <tr key={listing.id} className="hover:bg-neutral-900/60">
                    <td className="px-3 py-2">
                      <WatchButton
                        listingId={listing.id}
                        initial={watchedIds.has(listing.id)}
                        variant="icon"
                      />
                    </td>
                    <td className="px-3 py-2">
                      {listing.image_url ? (
                        <Image
                          src={listing.image_url}
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
                        href={`/listings/${listing.id}`}
                        className="font-medium hover:underline"
                      >
                        {listing.title ??
                          `${listing.make ?? ""} ${listing.model ?? ""}`.trim() ??
                          "—"}
                      </Link>
                      <div className="text-xs text-neutral-500">
                        {listing.year} · {listing.make} {listing.model} ·{" "}
                        {fmtKm(listing.km)} · {listing.region ?? "?"}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                      {clp(change.first_price)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium">
                      {clp(change.latest_price)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                      −{clp(Math.abs(change.abs_change))}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium">
                      <DropCell pct={change.pct_change} />
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-neutral-500">
                      {change.observations}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-neutral-500">
                      {age ?? "—"}d
                    </td>
                    <td className="px-3 py-2 text-neutral-400">{listing.source}</td>
                  </tr>
                );
              })}
              {items.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-3 py-10 text-center text-neutral-500">
                    No drops match these filters. Try a wider window or lower threshold.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <p className="text-xs text-neutral-500">
          Drops are computed from <code>listing_prices</code> — appended on every
          scrape. A listing must appear in our scrape at least twice with
          different prices to show up here. As coverage grows (weekly full sweep
          launches Sundays 03:00 UTC), this page will get much denser.
        </p>
      </main>
    </div>
  );
}

function DropCell({ pct }: { pct: number }) {
  const color =
    pct <= -20 ? "text-emerald-400" : pct <= -10 ? "text-emerald-500" : "text-emerald-600";
  return <span className={color}>{pct.toFixed(1)}%</span>;
}
