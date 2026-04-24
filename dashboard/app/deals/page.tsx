import Link from "next/link";
import Image from "next/image";
import { createClient } from "@/lib/supabase-server";
import { Nav } from "@/components/nav";
import { clp, km as fmtKm, daysSince } from "@/lib/format";

export const dynamic = "force-dynamic";

/**
 * Naive deal-scoring until market_stats rollup lands:
 *   For each active listing, compute the median price of peers
 *   matching (make, model, year ± 1). Rank by (price / median) ASC.
 *
 * SQL below uses a window function; requires `make`, `model`, `year` to be set.
 * Listings without all three are excluded. Minimum 4 peers per bucket to keep
 * the score meaningful.
 */
async function loadDeals() {
  const supabase = createClient();

  // Pull active listings with full identity
  const { data: rows } = await supabase
    .from("listings")
    .select(
      "id, source, url, title, make, model, version, year, km, latest_price_clp, first_seen_at, image_url, region",
    )
    .is("removed_at", null)
    .not("make", "is", null)
    .not("model", "is", null)
    .not("year", "is", null)
    .not("latest_price_clp", "is", null)
    .limit(10000);

  if (!rows) return [];

  // Bucket by (make, model, year) ± 1
  type R = (typeof rows)[number];
  const bucketKey = (r: R) => `${r.make}|${r.model}|${r.year}`;
  const priceByKey: Record<string, number[]> = {};
  for (const r of rows) {
    const k = bucketKey(r);
    (priceByKey[k] ??= []).push(r.latest_price_clp as number);
  }

  // Combine adjacent year buckets (±1) to grow sample sizes
  const adjacent = (r: R): number[] => {
    const keys = [
      `${r.make}|${r.model}|${(r.year as number) - 1}`,
      `${r.make}|${r.model}|${r.year}`,
      `${r.make}|${r.model}|${(r.year as number) + 1}`,
    ];
    const out: number[] = [];
    for (const k of keys) if (priceByKey[k]) out.push(...priceByKey[k]);
    return out;
  };

  const median = (arr: number[]) => {
    if (arr.length === 0) return 0;
    const s = [...arr].sort((a, b) => a - b);
    return s[Math.floor(s.length / 2)];
  };

  const withScore = rows
    .map((r) => {
      const peers = adjacent(r).filter((p) => p !== r.latest_price_clp);
      if (peers.length < 4) return null;
      const m = median(peers);
      const ratio = (r.latest_price_clp as number) / m;
      return {
        ...r,
        market_median: m,
        ratio,
        delta_pct: (ratio - 1) * 100,
        peer_count: peers.length,
      };
    })
    .filter(Boolean) as Array<
    R & { market_median: number; ratio: number; delta_pct: number; peer_count: number }
  >;

  withScore.sort((a, b) => a.ratio - b.ratio);
  return withScore.slice(0, 60);
}

export default async function Page() {
  const deals = await loadDeals();

  return (
    <div>
      <Nav pathname="/deals" />
      <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Top deals today
          </h1>
          <p className="mt-1 text-sm text-neutral-400">
            Ranked by price vs. median of the same make/model/year bucket.
            Showing only buckets with 4+ peer listings.
          </p>
        </div>

        <div className="overflow-hidden rounded-lg border border-neutral-800">
          <table className="min-w-full divide-y divide-neutral-800 text-sm">
            <thead className="bg-neutral-900 text-xs uppercase tracking-wider text-neutral-400">
              <tr>
                <th className="px-3 py-2 text-right">Rank</th>
                <th className="px-3 py-2 text-left">Photo</th>
                <th className="px-3 py-2 text-left">Listing</th>
                <th className="px-3 py-2 text-right">Price</th>
                <th className="px-3 py-2 text-right">Market</th>
                <th className="px-3 py-2 text-right">Δ</th>
                <th className="px-3 py-2 text-right">Peers</th>
                <th className="px-3 py-2 text-right">Km</th>
                <th className="px-3 py-2 text-right">Days</th>
                <th className="px-3 py-2 text-left">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-900 bg-neutral-950">
              {deals.map((d, i) => (
                <tr key={d.id} className="hover:bg-neutral-900/60">
                  <td className="px-3 py-2 text-right tabular-nums text-neutral-500">
                    #{i + 1}
                  </td>
                  <td className="px-3 py-2">
                    {d.image_url ? (
                      <Image
                        src={d.image_url}
                        alt=""
                        width={64}
                        height={48}
                        className="h-12 w-16 rounded object-cover"
                        unoptimized
                      />
                    ) : (
                      <div className="h-12 w-16 rounded bg-neutral-800" />
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <Link
                      href={`/listings/${d.id}`}
                      className="font-medium hover:underline"
                    >
                      {d.title ?? `${d.make} ${d.model}`}
                    </Link>
                    <div className="text-xs text-neutral-500">
                      {d.year} · {d.make} {d.model} · {d.region ?? "?"}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums font-medium">
                    {clp(d.latest_price_clp)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                    {clp(d.market_median)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums font-medium">
                    <span
                      className={
                        d.delta_pct < -20
                          ? "text-emerald-400"
                          : d.delta_pct < -10
                          ? "text-emerald-500"
                          : d.delta_pct < 0
                          ? "text-emerald-600"
                          : "text-neutral-400"
                      }
                    >
                      {d.delta_pct.toFixed(1)}%
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-neutral-500">
                    {d.peer_count}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {fmtKm(d.km)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-neutral-500">
                    {daysSince(d.first_seen_at) ?? "—"}d
                  </td>
                  <td className="px-3 py-2 text-neutral-400">{d.source}</td>
                </tr>
              ))}
              {deals.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-3 py-10 text-center text-neutral-500">
                    Not enough data yet for deal scoring. Come back after a few
                    daily scrapes have run.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}
