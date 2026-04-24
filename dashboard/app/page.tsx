import { createClient } from "@/lib/supabase-server";
import { Nav } from "@/components/nav";
import { SOURCES } from "@/lib/types";
import { clp, relTime } from "@/lib/format";

export const dynamic = "force-dynamic";

type SourceHealth = {
  source: string;
  active: number;
  last_run_at: string | null;
  last_status: string | null;
  last_fetched: number | null;
  last_error: string | null;
};

async function loadOverview() {
  const supabase = createClient();

  // Active listing total
  const { count: totalActive } = await supabase
    .from("listings")
    .select("*", { count: "exact", head: true })
    .is("removed_at", null);

  // Active count per source (one query per source — small & fast)
  const perSource: SourceHealth[] = await Promise.all(
    SOURCES.map(async (source) => {
      const { count } = await supabase
        .from("listings")
        .select("*", { count: "exact", head: true })
        .is("removed_at", null)
        .eq("source", source);

      const { data: lastRun } = await supabase
        .from("scrape_runs")
        .select("started_at, status, rows_fetched, error")
        .eq("source", source)
        .order("started_at", { ascending: false })
        .limit(1)
        .maybeSingle();

      return {
        source,
        active: count ?? 0,
        last_run_at: lastRun?.started_at ?? null,
        last_status: lastRun?.status ?? null,
        last_fetched: lastRun?.rows_fetched ?? null,
        last_error: lastRun?.error ?? null,
      };
    }),
  );

  // Today's pulse: counts of rows first_seen / removed in the last 24h + price changes
  const since = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
  const { count: addedToday } = await supabase
    .from("listings")
    .select("*", { count: "exact", head: true })
    .gte("first_seen_at", since);
  const { count: removedToday } = await supabase
    .from("listings")
    .select("*", { count: "exact", head: true })
    .gte("removed_at", since);
  const { count: priceChanges } = await supabase
    .from("listing_prices")
    .select("*", { count: "exact", head: true })
    .gte("observed_at", since);

  // Avg price (active)
  const { data: priceSample } = await supabase
    .from("listings")
    .select("latest_price_clp")
    .is("removed_at", null)
    .not("latest_price_clp", "is", null)
    .order("latest_price_clp", { ascending: false })
    .limit(5000);
  const prices = (priceSample ?? [])
    .map((r) => r.latest_price_clp as number)
    .filter((v) => v > 0);
  const medianPrice =
    prices.length > 0 ? prices[Math.floor(prices.length / 2)] : null;

  return {
    totalActive: totalActive ?? 0,
    addedToday: addedToday ?? 0,
    removedToday: removedToday ?? 0,
    priceChanges: priceChanges ?? 0,
    medianPrice,
    perSource,
  };
}

function healthColor(h: SourceHealth): string {
  if (!h.last_run_at) return "bg-neutral-600";
  const ageH = (Date.now() - new Date(h.last_run_at).getTime()) / 3_600_000;
  if (h.last_status === "failed") return "bg-red-500";
  if (ageH > 36) return "bg-yellow-500";
  if (h.last_fetched === 0) return "bg-yellow-500";
  return "bg-emerald-500";
}

export default async function Page() {
  const data = await loadOverview();
  const staleSources = data.perSource.filter((h) => {
    if (!h.last_run_at) return true;
    const ageH = (Date.now() - new Date(h.last_run_at).getTime()) / 3_600_000;
    return ageH > 36 || h.last_status === "failed";
  });

  return (
    <div>
      <Nav pathname="/" />
      <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
        {staleSources.length > 0 && (
          <div className="rounded-md border border-yellow-900 bg-yellow-950/40 px-4 py-3 text-sm text-yellow-200">
            ⚠️ {staleSources.length} source{staleSources.length === 1 ? "" : "s"}{" "}
            need{staleSources.length === 1 ? "s" : ""} attention:{" "}
            {staleSources.map((s) => s.source).join(", ")}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <StatCard label="Active listings" value={fmt(data.totalActive)} />
          <StatCard label="Added (24h)" value={`+${fmt(data.addedToday)}`} />
          <StatCard label="Removed (24h)" value={`-${fmt(data.removedToday)}`} />
          <StatCard label="Price changes (24h)" value={fmt(data.priceChanges)} />
          <StatCard label="Median price" value={clp(data.medianPrice)} />
        </div>

        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-400">
            Sources
          </h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
            {data.perSource.map((s) => (
              <SourceCard key={s.source} h={s} />
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function SourceCard({ h }: { h: SourceHealth }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${healthColor(h)}`} />
            <span className="font-medium">{h.source}</span>
          </div>
          <div className="mt-1 text-xs text-neutral-500">
            {h.active} active · last run {relTime(h.last_run_at)}
            {h.last_fetched != null && ` · ${h.last_fetched} rows`}
          </div>
        </div>
        <div className="text-xs uppercase text-neutral-500">
          {h.last_status ?? "—"}
        </div>
      </div>
      {h.last_error && (
        <div className="mt-2 line-clamp-2 rounded bg-red-950/40 px-2 py-1 text-xs text-red-300">
          {h.last_error}
        </div>
      )}
    </div>
  );
}

function fmt(n: number): string {
  return new Intl.NumberFormat("es-CL").format(n);
}
