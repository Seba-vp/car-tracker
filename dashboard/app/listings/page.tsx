import Link from "next/link";
import Image from "next/image";
import { createClient } from "@/lib/supabase-server";
import { Nav } from "@/components/nav";
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

async function loadListings(params: Params["searchParams"]) {
  const supabase = createClient();

  let q = supabase
    .from("listings")
    .select(
      "id, source, source_id, url, title, make, model, version, year, km, fuel_type, transmission, body_type, region, latest_price_clp, first_seen_at, image_url",
      { count: "exact" },
    )
    .is("removed_at", null)
    .not("latest_price_clp", "is", null);

  if (params.make) q = q.ilike("make", params.make);
  if (params.model) q = q.ilike("model", `%${params.model}%`);
  if (params.yearMin) q = q.gte("year", +params.yearMin);
  if (params.yearMax) q = q.lte("year", +params.yearMax);
  if (params.priceMin) q = q.gte("latest_price_clp", +params.priceMin);
  if (params.priceMax) q = q.lte("latest_price_clp", +params.priceMax);
  if (params.kmMax) q = q.lte("km", +params.kmMax);
  if (params.fuel) q = q.eq("fuel_type", params.fuel);
  if (params.region) q = q.ilike("region", `%${params.region}%`);
  if (params.source) q = q.eq("source", params.source);
  if (params.q) q = q.or(`title.ilike.%${params.q}%,model.ilike.%${params.q}%`);

  const sort = params.sort ?? "price_asc";
  if (sort === "price_asc") q = q.order("latest_price_clp", { ascending: true });
  else if (sort === "price_desc") q = q.order("latest_price_clp", { ascending: false });
  else if (sort === "newest") q = q.order("first_seen_at", { ascending: false });
  else if (sort === "km_asc") q = q.order("km", { ascending: true, nullsFirst: false });

  const page = Math.max(1, +(params.page ?? "1"));
  const from = (page - 1) * PAGE_SIZE;
  q = q.range(from, from + PAGE_SIZE - 1);

  const { data, count } = await q;
  return { rows: (data ?? []) as Partial<Listing>[], total: count ?? 0, page };
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

  const uniq = (arr: { [k: string]: string | null }[], key: string) =>
    Array.from(new Set(arr.map((r) => r[key]).filter(Boolean))).sort() as string[];

  return {
    makes: uniq(makes ?? [], "make"),
    fuels: uniq(fuels ?? [], "fuel_type"),
    regions: uniq(regions ?? [], "region"),
  };
}

export default async function Page({ searchParams }: Params) {
  const [{ rows, total, page }, filters] = await Promise.all([
    loadListings(searchParams),
    loadFilterOptions(),
  ]);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <Nav pathname="/listings" />
      <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
        <FilterBar filters={filters} current={searchParams} />

        <div className="flex items-center justify-between text-sm text-neutral-400">
          <span>{total.toLocaleString("es-CL")} listings</span>
          <span>
            page {page} of {totalPages}
          </span>
        </div>

        <div className="overflow-hidden rounded-lg border border-neutral-800">
          <table className="min-w-full divide-y divide-neutral-800 text-sm">
            <thead className="bg-neutral-900 text-xs uppercase tracking-wider text-neutral-400">
              <tr>
                <th className="px-3 py-2 text-left">Photo</th>
                <th className="px-3 py-2 text-left">Title</th>
                <th className="px-3 py-2 text-right">Year</th>
                <th className="px-3 py-2 text-right">Km</th>
                <th className="px-3 py-2 text-right">Price</th>
                <th className="px-3 py-2 text-left">Source</th>
                <th className="px-3 py-2 text-right">Days</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-900 bg-neutral-950">
              {rows.map((r) => {
                const age = daysSince(r.first_seen_at);
                return (
                  <tr key={r.id} className="hover:bg-neutral-900/60">
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
                    <td className="px-3 py-2 text-neutral-400">{r.source}</td>
                    <td className="px-3 py-2 text-right text-neutral-500 tabular-nums">
                      {age ?? "—"}d
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-10 text-center text-neutral-500">
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
        <option value="price_asc">Price ↑</option>
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
