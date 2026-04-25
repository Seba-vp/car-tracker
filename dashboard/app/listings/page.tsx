import Link from "next/link";
import Image from "next/image";
import { createClient } from "@/lib/supabase-server";
import { Nav } from "@/components/nav";
import { WatchButton } from "@/components/watch-button";
import type { Listing } from "@/lib/types";
import { clp, km as fmtKm, daysSince } from "@/lib/format";

export const dynamic = "force-dynamic";

type Params = {
  searchParams: {
    make?: string;
    model?: string;
    yearMin?: string;
    yearMax?: string;
    priceMin?: string;
    priceMax?: string;
    kmMin?: string;
    kmMax?: string;
    fuel?: string;
    region?: string;
    source?: string;
    sort?: string;
    q?: string;
    page?: string;
  };
};

const PAGE_SIZE = 50;
const STATS_SAMPLE_LIMIT = 5000;

// Apply the same filter set to either the paged query or the stats-sample query.
function applyFilters<T extends { [k: string]: any }>(q: T, p: Params["searchParams"]): T {
  let out: any = q;
  if (p.make) out = out.ilike("make", p.make);
  if (p.model) out = out.ilike("model", `%${p.model}%`);
  if (p.yearMin) out = out.gte("year", +p.yearMin);
  if (p.yearMax) out = out.lte("year", +p.yearMax);
  if (p.priceMin) out = out.gte("latest_price_clp", +p.priceMin);
  if (p.priceMax) out = out.lte("latest_price_clp", +p.priceMax);
  if (p.kmMin) out = out.gte("km", +p.kmMin);
  if (p.kmMax) out = out.lte("km", +p.kmMax);
  if (p.fuel) out = out.eq("fuel_type", p.fuel);
  if (p.region) out = out.ilike("region", `%${p.region}%`);
  if (p.source) out = out.eq("source", p.source);
  if (p.q) out = out.or(`title.ilike.%${p.q}%,model.ilike.%${p.q}%`);
  return out as T;
}

type Stats = {
  n: number;
  mean: number;
  median: number;
  p25: number;
  p75: number;
  stddev: number;
  min: number;
  max: number;
};

function computeStats(prices: number[]): Stats | null {
  if (prices.length === 0) return null;
  const s = [...prices].sort((a, b) => a - b);
  const q = (p: number) => s[Math.min(s.length - 1, Math.max(0, Math.round(p * (s.length - 1))))];
  const mean = s.reduce((a, b) => a + b, 0) / s.length;
  const variance = s.length > 1 ? s.reduce((a, b) => a + (b - mean) ** 2, 0) / (s.length - 1) : 0;
  return {
    n: s.length,
    mean: Math.round(mean),
    median: q(0.5),
    p25: q(0.25),
    p75: q(0.75),
    stddev: Math.round(Math.sqrt(variance)),
    min: s[0],
    max: s[s.length - 1],
  };
}

async function load(params: Params["searchParams"], userId: string | null) {
  const supabase = createClient();

  const base = supabase
    .from("listings")
    .select(
      "id, source, source_id, url, title, make, model, version, year, km, fuel_type, transmission, body_type, region, latest_price_clp, first_seen_at, image_url",
      { count: "exact" },
    )
    .is("removed_at", null)
    .not("latest_price_clp", "is", null);
  const filtered = applyFilters(base, params);

  const sort = params.sort ?? "price_asc";
  let pageQ = filtered;
  if (sort === "price_asc") pageQ = pageQ.order("latest_price_clp", { ascending: true });
  else if (sort === "price_desc") pageQ = pageQ.order("latest_price_clp", { ascending: false });
  else if (sort === "newest") pageQ = pageQ.order("first_seen_at", { ascending: false });
  else if (sort === "km_asc")
    pageQ = pageQ.order("km", { ascending: true, nullsFirst: false });

  const page = Math.max(1, +(params.page ?? "1"));
  const from = (page - 1) * PAGE_SIZE;
  pageQ = pageQ.range(from, from + PAGE_SIZE - 1);

  // Stats sample — up to STATS_SAMPLE_LIMIT prices matching the filters.
  const statsBase = supabase
    .from("listings")
    .select("latest_price_clp")
    .is("removed_at", null)
    .not("latest_price_clp", "is", null)
    .limit(STATS_SAMPLE_LIMIT);
  const statsQ = applyFilters(statsBase, params);

  // Watchlist — only the listings on this page (don't fetch whole thing)
  const watchQ = userId
    ? supabase.from("watchlist").select("listing_id").eq("user_id", userId)
    : null;

  const [{ data: rows, count }, { data: statsRows }, watchRes] = await Promise.all([
    pageQ,
    statsQ,
    watchQ ?? Promise.resolve({ data: [] as { listing_id: number }[] }),
  ]);

  const stats = computeStats(
    (statsRows ?? []).map((r) => r.latest_price_clp as number).filter((v) => v > 0),
  );
  const watchedIds = new Set<number>((watchRes?.data ?? []).map((r: any) => r.listing_id));

  return {
    rows: (rows ?? []) as Partial<Listing>[],
    total: count ?? 0,
    page,
    stats,
    watchedIds,
    sort,
  };
}

async function loadFilterOptions() {
  const supabase = createClient();
  const [{ data: makes }, { data: fuels }, { data: regions }] = await Promise.all([
    supabase
      .from("listings")
      .select("make")
      .is("removed_at", null)
      .not("make", "is", null)
      .limit(5000),
    supabase
      .from("listings")
      .select("fuel_type")
      .is("removed_at", null)
      .not("fuel_type", "is", null)
      .limit(5000),
    supabase
      .from("listings")
      .select("region")
      .is("removed_at", null)
      .not("region", "is", null)
      .limit(5000),
  ]);
  const uniq = (arr: { [k: string]: any }[], key: string) =>
    Array.from(new Set(arr.map((r) => r[key]).filter(Boolean))).sort() as string[];
  return {
    makes: uniq(makes ?? [], "make"),
    fuels: uniq(fuels ?? [], "fuel_type"),
    regions: uniq(regions ?? [], "region"),
  };
}

export default async function Page({ searchParams }: Params) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  const userId = user?.id ?? null;

  const [data, filters] = await Promise.all([
    load(searchParams, userId),
    loadFilterOptions(),
  ]);
  const { rows, total, page, stats, watchedIds, sort } = data;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // Rank of first row on this page within the whole filtered cohort when
  // sorted price_asc. For other sorts the rank number still shows but is
  // just the row's page position.
  const rankBase = (page - 1) * PAGE_SIZE;

  return (
    <div>
      <Nav pathname="/listings" />
      <main className="mx-auto max-w-7xl space-y-5 px-6 py-8">
        <FilterBar filters={filters} current={searchParams} />

        <CohortStats stats={stats} />

        <div className="flex items-center justify-between text-sm text-neutral-400">
          <span>{total.toLocaleString("es-CL")} listings in cohort</span>
          <span>
            page {page} of {totalPages} · sorted by{" "}
            <span className="text-neutral-200">{prettySort(sort)}</span>
          </span>
        </div>

        <div className="overflow-hidden rounded-lg border border-neutral-800">
          <table className="min-w-full divide-y divide-neutral-800 text-sm">
            <thead className="bg-neutral-900 text-xs uppercase tracking-wider text-neutral-400">
              <tr>
                <th className="px-3 py-2 text-right w-8">#</th>
                <th className="px-3 py-2 text-left w-10"></th>
                <th className="px-3 py-2 text-left">Photo</th>
                <th className="px-3 py-2 text-left">Title</th>
                <th className="px-3 py-2 text-right">Year</th>
                <th className="px-3 py-2 text-right">Km</th>
                <th className="px-3 py-2 text-right">Price</th>
                <th className="px-3 py-2 text-right">Δ median</th>
                <th className="px-3 py-2 text-right">Δ mean</th>
                <th className="px-3 py-2 text-left">Source</th>
                <th className="px-3 py-2 text-right">Days</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-900 bg-neutral-950">
              {rows.map((r, idx) => {
                const age = daysSince(r.first_seen_at);
                const rank = sort === "price_asc" ? rankBase + idx + 1 : null;
                const delta =
                  stats && r.latest_price_clp
                    ? ((r.latest_price_clp - stats.median) / stats.median) * 100
                    : null;
                const deltaMean =
                  stats && r.latest_price_clp && stats.mean
                    ? ((r.latest_price_clp - stats.mean) / stats.mean) * 100
                    : null;
                return (
                  <tr key={r.id} className="hover:bg-neutral-900/60">
                    <td className="px-3 py-2 text-right tabular-nums text-neutral-500">
                      {rank ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      {userId && r.id != null && (
                        <WatchButton
                          listingId={r.id as number}
                          initial={watchedIds.has(r.id as number)}
                          variant="icon"
                        />
                      )}
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
                        className="font-medium text-white hover:underline"
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
                    <td className="px-3 py-2 text-right tabular-nums">
                      <DeltaCell delta={delta} />
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      <DeltaCell delta={deltaMean} />
                    </td>
                    <td className="px-3 py-2 text-neutral-400">{r.source}</td>
                    <td className="px-3 py-2 text-right text-neutral-500 tabular-nums">
                      {age ?? "—"}d
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-3 py-10 text-center text-neutral-500">
                    No listings match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <Pager searchParams={searchParams} page={page} totalPages={totalPages} />
      </main>
    </div>
  );
}

function prettySort(s: string) {
  return (
    { price_asc: "Price ↑", price_desc: "Price ↓", newest: "Newest listed", km_asc: "Lowest km" } as Record<string, string>
  )[s] ?? s;
}

function CohortStats({ stats }: { stats: Stats | null }) {
  if (!stats || stats.n < 2) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-3 text-sm text-neutral-500">
        Apply filters to see cohort statistics.
      </div>
    );
  }
  const cells: Array<{ label: string; value: string }> = [
    { label: "N", value: stats.n.toLocaleString("es-CL") },
    { label: "Mean", value: clp(stats.mean) },
    { label: "Median", value: clp(stats.median) },
    { label: "P25", value: clp(stats.p25) },
    { label: "P75", value: clp(stats.p75) },
    { label: "σ", value: clp(stats.stddev) },
    { label: "Min", value: clp(stats.min) },
    { label: "Max", value: clp(stats.max) },
  ];
  return (
    <div className="grid grid-cols-2 gap-2 rounded-lg border border-neutral-800 bg-neutral-950 p-3 md:grid-cols-8">
      {cells.map((c) => (
        <div key={c.label} className="text-center">
          <div className="text-[10px] uppercase tracking-wider text-neutral-500">
            {c.label}
          </div>
          <div className="text-sm tabular-nums font-medium">{c.value}</div>
        </div>
      ))}
    </div>
  );
}

function DeltaCell({ delta }: { delta: number | null }) {
  if (delta == null) return <span className="text-neutral-600">—</span>;
  const color =
    delta < -20
      ? "text-emerald-400"
      : delta < -10
      ? "text-emerald-500"
      : delta < 0
      ? "text-emerald-600"
      : delta > 20
      ? "text-red-400"
      : delta > 10
      ? "text-red-500"
      : "text-neutral-400";
  return (
    <span className={`${color} font-medium`}>
      {delta >= 0 ? "+" : ""}
      {delta.toFixed(1)}%
    </span>
  );
}

function FilterBar({
  filters,
  current,
}: {
  filters: { makes: string[]; fuels: string[]; regions: string[] };
  current: Params["searchParams"];
}) {
  return (
    <form
      method="GET"
      className="grid grid-cols-2 gap-2 rounded-lg border border-neutral-800 bg-neutral-950 p-4 md:grid-cols-6"
    >
      <input
        name="q"
        placeholder="Search…"
        defaultValue={current.q ?? ""}
        className="col-span-2 rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      />
      <select
        name="make"
        defaultValue={current.make ?? ""}
        className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      >
        <option value="">Any make</option>
        {filters.makes.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
      <input
        name="model"
        placeholder="Model"
        defaultValue={current.model ?? ""}
        className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      />
      <select
        name="fuel"
        defaultValue={current.fuel ?? ""}
        className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      >
        <option value="">Any fuel</option>
        {filters.fuels.map((f) => (
          <option key={f} value={f}>
            {f}
          </option>
        ))}
      </select>
      <select
        name="region"
        defaultValue={current.region ?? ""}
        className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      >
        <option value="">Any region</option>
        {filters.regions.map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>

      <input
        name="yearMin"
        type="number"
        placeholder="Year min"
        defaultValue={current.yearMin ?? ""}
        className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      />
      <input
        name="yearMax"
        type="number"
        placeholder="Year max"
        defaultValue={current.yearMax ?? ""}
        className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      />
      <input
        name="priceMin"
        type="number"
        placeholder="$ min"
        defaultValue={current.priceMin ?? ""}
        className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      />
      <input
        name="priceMax"
        type="number"
        placeholder="$ max"
        defaultValue={current.priceMax ?? ""}
        className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      />
      <input
        name="kmMin"
        type="number"
        placeholder="km min"
        defaultValue={current.kmMin ?? ""}
        className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      />
      <input
        name="kmMax"
        type="number"
        placeholder="km max"
        defaultValue={current.kmMax ?? ""}
        className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      />
      <select
        name="sort"
        defaultValue={current.sort ?? "price_asc"}
        className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      >
        <option value="price_asc">Price ↑ (rank by deal)</option>
        <option value="price_desc">Price ↓</option>
        <option value="newest">Newest listed</option>
        <option value="km_asc">Lowest km</option>
      </select>

      <button className="col-span-2 rounded bg-white px-3 py-1 text-sm font-medium text-black hover:bg-neutral-200 md:col-span-1">
        Filter
      </button>
    </form>
  );
}

function Pager({
  searchParams,
  page,
  totalPages,
}: {
  searchParams: Params["searchParams"];
  page: number;
  totalPages: number;
}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(searchParams)) {
    if (v && k !== "page") qs.set(k, String(v));
  }
  const mkHref = (p: number) => {
    const q = new URLSearchParams(qs);
    q.set("page", String(p));
    return `?${q.toString()}`;
  };
  const prev = Math.max(1, page - 1);
  const next = Math.min(totalPages, page + 1);
  return (
    <div className="flex items-center justify-center gap-2 text-sm">
      <Link
        href={mkHref(prev)}
        className={`rounded border border-neutral-800 px-3 py-1 ${
          page === 1 ? "pointer-events-none opacity-40" : "hover:bg-neutral-900"
        }`}
      >
        ← Prev
      </Link>
      <span className="tabular-nums text-neutral-400">
        {page} / {totalPages}
      </span>
      <Link
        href={mkHref(next)}
        className={`rounded border border-neutral-800 px-3 py-1 ${
          page === totalPages ? "pointer-events-none opacity-40" : "hover:bg-neutral-900"
        }`}
      >
        Next →
      </Link>
    </div>
  );
}
