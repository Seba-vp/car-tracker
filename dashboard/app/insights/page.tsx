import { createClient } from "@/lib/supabase-server";
import { Nav } from "@/components/nav";
import { clp, km as fmtKm } from "@/lib/format";
import { DepreciationChart, type YearPoint } from "@/components/depreciation-chart";

export const dynamic = "force-dynamic";

type BrandRow = {
  make: string;
  n_listings: number;
  n_models: number;
  oldest_year: number | null;
  newest_year: number | null;
  median_price_clp: number | null;
  avg_price_clp: number | null;
  n_gasolina: number;
  n_diesel: number;
  n_hibrido: number;
  n_electrico: number;
  n_dealer: number;
  n_private: number;
  sources_seen: string[];
};

type ModelRow = {
  make: string;
  model: string;
  n_listings: number;
  oldest_year: number | null;
  newest_year: number | null;
  median_price_clp: number | null;
  p25_price_clp: number | null;
  p75_price_clp: number | null;
  avg_km: number | null;
  body_type: string | null;
  primary_fuel_type: string | null;
  primary_transmission: string | null;
  n_dealer: number;
  n_private: number;
  year_price_json: Record<string, { n: number; median: number }> | null;
};

async function load(selectedMakeModel?: string) {
  const supabase = createClient();

  const [brandsRes, modelsRes] = await Promise.all([
    supabase
      .from("brand_rollup")
      .select("*")
      .order("n_listings", { ascending: false })
      .limit(50),
    supabase
      .from("model_rollup")
      .select("*")
      .order("n_listings", { ascending: false })
      .limit(200),
  ]);

  const brands = (brandsRes.data ?? []) as BrandRow[];
  const models = (modelsRes.data ?? []) as ModelRow[];

  // Pick the selected model for the depreciation chart, or fall back to
  // the single most-listed model.
  let selected: ModelRow | null = null;
  if (selectedMakeModel) {
    const [make, ...modelParts] = selectedMakeModel.split("/");
    const model = modelParts.join("/");
    selected = models.find((m) => m.make === make && m.model === model) ?? null;
  }
  if (!selected && models.length) selected = models[0];

  const yearPoints: YearPoint[] = [];
  if (selected?.year_price_json) {
    const entries = Object.entries(selected.year_price_json)
      .map(([yr, v]) => ({ year: Number(yr), median: v.median, n: v.n }))
      .filter((p) => Number.isFinite(p.year) && p.median > 0 && p.n >= 2)
      .sort((a, b) => a.year - b.year);
    yearPoints.push(...entries);
  }

  return { brands, models, selected, yearPoints };
}

export default async function Page({
  searchParams,
}: {
  searchParams: { model?: string };
}) {
  const { brands, models, selected, yearPoints } = await load(
    searchParams.model,
  );

  return (
    <div>
      <Nav pathname="/insights" />
      <main className="mx-auto max-w-7xl space-y-8 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">Insights</h1>
          <p className="mt-1 text-sm text-neutral-400">
            Aggregated view of the {brands.length} most-listed brands and top{" "}
            {models.length} models in the active market.
          </p>
        </header>

        {/* Depreciation of the selected model */}
        {selected && (
          <section className="rounded-lg border border-neutral-800 bg-neutral-950 p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-4">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-neutral-400">
                Year × Median price
              </h2>
              <ModelPicker
                models={models.slice(0, 50)}
                selected={selected}
              />
            </div>
            <div className="mt-4 flex flex-col gap-4 md:flex-row">
              <div className="md:w-1/3 space-y-2 text-sm">
                <div className="text-lg font-semibold">
                  {selected.make} {selected.model}
                </div>
                <KV k="Listings" v={selected.n_listings.toString()} />
                <KV
                  k="Year range"
                  v={`${selected.oldest_year ?? "?"} – ${selected.newest_year ?? "?"}`}
                />
                <KV k="Median price" v={clp(selected.median_price_clp)} />
                <KV
                  k="IQR (p25–p75)"
                  v={`${clp(selected.p25_price_clp)} – ${clp(selected.p75_price_clp)}`}
                />
                <KV k="Avg km" v={fmtKm(selected.avg_km)} />
                <KV k="Body" v={selected.body_type ?? "—"} />
                <KV k="Fuel" v={selected.primary_fuel_type ?? "—"} />
                <KV k="Trans" v={selected.primary_transmission ?? "—"} />
                <KV
                  k="Dealer / Private"
                  v={`${selected.n_dealer} / ${selected.n_private}`}
                />
              </div>
              <div className="flex-1">
                <DepreciationChart data={yearPoints} />
                <p className="mt-2 text-xs text-neutral-500">
                  Each point is the median listed price in that model year.
                  Only years with ≥2 active listings shown.
                </p>
              </div>
            </div>
          </section>
        )}

        {/* Brand leaderboard */}
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-400">
            Brand leaderboard
          </h2>
          <div className="overflow-hidden rounded-lg border border-neutral-800">
            <table className="min-w-full divide-y divide-neutral-800 text-sm">
              <thead className="bg-neutral-900 text-xs uppercase tracking-wider text-neutral-400">
                <tr>
                  <th className="px-3 py-2 text-left">Make</th>
                  <th className="px-3 py-2 text-right">Listings</th>
                  <th className="px-3 py-2 text-right">Models</th>
                  <th className="px-3 py-2 text-right">Median</th>
                  <th className="px-3 py-2 text-right">Years</th>
                  <th className="px-3 py-2 text-right">Dealer/Private</th>
                  <th className="px-3 py-2 text-left">Fuel mix</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-900 bg-neutral-950">
                {brands.map((b) => (
                  <tr key={b.make} className="hover:bg-neutral-900/60">
                    <td className="px-3 py-2 font-medium">{b.make}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {b.n_listings.toLocaleString("es-CL")}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                      {b.n_models}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium">
                      {clp(b.median_price_clp)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                      {b.oldest_year}–{b.newest_year}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                      {b.n_dealer}/{b.n_private}
                    </td>
                    <td className="px-3 py-2">
                      <FuelMix b={b} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Model leaderboard */}
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-400">
            Model leaderboard
          </h2>
          <div className="overflow-hidden rounded-lg border border-neutral-800">
            <table className="min-w-full divide-y divide-neutral-800 text-sm">
              <thead className="bg-neutral-900 text-xs uppercase tracking-wider text-neutral-400">
                <tr>
                  <th className="px-3 py-2 text-left">Make</th>
                  <th className="px-3 py-2 text-left">Model</th>
                  <th className="px-3 py-2 text-right">Listings</th>
                  <th className="px-3 py-2 text-right">Years</th>
                  <th className="px-3 py-2 text-right">Median</th>
                  <th className="px-3 py-2 text-right">IQR</th>
                  <th className="px-3 py-2 text-left">Body</th>
                  <th className="px-3 py-2 text-left">Fuel</th>
                  <th className="px-3 py-2 text-right">D/P</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-900 bg-neutral-950">
                {models.slice(0, 60).map((m) => (
                  <tr
                    key={`${m.make}|${m.model}`}
                    className="hover:bg-neutral-900/60"
                  >
                    <td className="px-3 py-2 font-medium">{m.make}</td>
                    <td className="px-3 py-2">
                      <a
                        href={`/insights?model=${encodeURIComponent(`${m.make}/${m.model}`)}`}
                        className="hover:underline"
                      >
                        {m.model}
                      </a>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {m.n_listings}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
                      {m.oldest_year}–{m.newest_year}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium">
                      {clp(m.median_price_clp)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-neutral-500">
                      {clp(m.p25_price_clp)} – {clp(m.p75_price_clp)}
                    </td>
                    <td className="px-3 py-2 text-neutral-400">
                      {m.body_type ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-neutral-400">
                      {m.primary_fuel_type ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-neutral-500">
                      {m.n_dealer}/{m.n_private}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-4 text-sm">
      <span className="text-neutral-500">{k}</span>
      <span className="tabular-nums">{v}</span>
    </div>
  );
}

function FuelMix({ b }: { b: BrandRow }) {
  const total = b.n_gasolina + b.n_diesel + b.n_hibrido + b.n_electrico;
  if (!total) return <span className="text-neutral-500">—</span>;
  const segments: Array<{ label: string; n: number; color: string }> = [
    { label: "gas", n: b.n_gasolina, color: "bg-amber-500" },
    { label: "dsl", n: b.n_diesel, color: "bg-sky-500" },
    { label: "hyb", n: b.n_hibrido, color: "bg-emerald-500" },
    { label: "ev", n: b.n_electrico, color: "bg-violet-500" },
  ].filter((s) => s.n > 0);
  return (
    <div className="flex h-4 w-40 overflow-hidden rounded" title={segments.map((s) => `${s.label}: ${s.n}`).join(" · ")}>
      {segments.map((s) => (
        <div
          key={s.label}
          className={s.color}
          style={{ width: `${(s.n / total) * 100}%` }}
        />
      ))}
    </div>
  );
}

function ModelPicker({
  models,
  selected,
}: {
  models: ModelRow[];
  selected: ModelRow;
}) {
  const currentKey = `${selected.make}/${selected.model}`;
  return (
    <form method="GET" className="flex items-center gap-2 text-sm">
      <label className="text-neutral-500">Model:</label>
      <select
        name="model"
        defaultValue={currentKey}
        className="rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm"
      >
        {models.map((m) => {
          const k = `${m.make}/${m.model}`;
          return (
            <option key={k} value={k}>
              {m.make} {m.model}  ·  {m.n_listings} listings
            </option>
          );
        })}
      </select>
      <button className="rounded bg-white px-3 py-1 text-xs font-medium text-black hover:bg-neutral-200">
        Show
      </button>
    </form>
  );
}
