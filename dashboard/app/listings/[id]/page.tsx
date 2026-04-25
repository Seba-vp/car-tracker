import { notFound } from "next/navigation";
import Image from "next/image";
import { createClient } from "@/lib/supabase-server";
import { Nav } from "@/components/nav";
import { PriceChart } from "@/components/price-chart";
import { WatchButton } from "@/components/watch-button";
import { clp, km as fmtKm, daysSince, relTime } from "@/lib/format";

export const dynamic = "force-dynamic";

async function load(id: number) {
  const supabase = createClient();
  const { data: listing } = await supabase
    .from("listings")
    .select("*")
    .eq("id", id)
    .maybeSingle();
  if (!listing) return null;

  const {
    data: { user },
  } = await supabase.auth.getUser();

  let watched = false;
  if (user) {
    const { data: w } = await supabase
      .from("watchlist")
      .select("listing_id")
      .eq("user_id", user.id)
      .eq("listing_id", id)
      .maybeSingle();
    watched = !!w;
  }

  const { data: prices } = await supabase
    .from("listing_prices")
    .select("observed_at, price_clp")
    .eq("listing_id", id)
    .order("observed_at", { ascending: true });

  // Market median for this make/model/year bucket (rough)
  let marketMedian: number | null = null;
  if (listing.make && listing.model && listing.year) {
    const { data: peers } = await supabase
      .from("listings")
      .select("latest_price_clp")
      .is("removed_at", null)
      .eq("make", listing.make)
      .eq("model", listing.model)
      .gte("year", listing.year - 1)
      .lte("year", listing.year + 1)
      .not("latest_price_clp", "is", null)
      .neq("id", id)
      .limit(500);
    const arr = (peers ?? [])
      .map((r) => r.latest_price_clp as number)
      .sort((a, b) => a - b);
    if (arr.length >= 3) {
      marketMedian = arr[Math.floor(arr.length / 2)];
    }
  }

  return { listing, prices: prices ?? [], marketMedian, watched };
}

export default async function Page({ params }: { params: { id: string } }) {
  const id = Number(params.id);
  if (!Number.isFinite(id)) notFound();
  const data = await load(id);
  if (!data) notFound();
  const { listing, prices, marketMedian, watched } = data;

  const price = listing.latest_price_clp as number | null;
  const delta =
    price && marketMedian
      ? ((price - marketMedian) / marketMedian) * 100
      : null;

  return (
    <div>
      <Nav pathname="/listings" />
      <main className="mx-auto max-w-5xl space-y-6 px-6 py-8">
        <div className="flex flex-col gap-6 md:flex-row">
          <div className="md:w-1/2">
            {listing.image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <Image
                src={listing.image_url}
                alt={listing.title ?? ""}
                width={600}
                height={400}
                className="w-full rounded-lg border border-neutral-800 object-cover"
                unoptimized
              />
            ) : (
              <div className="flex aspect-video items-center justify-center rounded-lg border border-neutral-800 bg-neutral-900 text-neutral-600">
                no image
              </div>
            )}
          </div>
          <div className="md:w-1/2">
            <h1 className="text-2xl font-semibold tracking-tight">
              {listing.title ??
                `${listing.make ?? ""} ${listing.model ?? ""}`.trim()}
            </h1>
            <div className="mt-1 text-sm text-neutral-400">
              {listing.make} · {listing.model} · {listing.version ?? ""} ·{" "}
              {listing.year ?? "?"}
            </div>
            <div className="mt-4 flex items-baseline gap-3">
              <div className="text-3xl font-semibold tabular-nums">
                {clp(price)}
              </div>
              {delta != null && (
                <div
                  className={`rounded px-2 py-1 text-xs font-medium ${
                    delta < -10
                      ? "bg-emerald-950 text-emerald-300"
                      : delta < 0
                      ? "bg-emerald-900/40 text-emerald-400"
                      : delta > 10
                      ? "bg-red-950 text-red-300"
                      : "bg-neutral-800 text-neutral-400"
                  }`}
                >
                  {delta > 0 ? "+" : ""}
                  {delta.toFixed(1)}% vs. market median
                </div>
              )}
            </div>
            <dl className="mt-6 grid grid-cols-2 gap-y-3 gap-x-6 text-sm">
              <Field label="Km">{fmtKm(listing.km)}</Field>
              <Field label="Fuel">{listing.fuel_type ?? "—"}</Field>
              <Field label="Transmission">{listing.transmission ?? "—"}</Field>
              <Field label="Body">{listing.body_type ?? "—"}</Field>
              <Field label="Region">{listing.region ?? "—"}</Field>
              <Field label="Commune">{listing.commune ?? "—"}</Field>
              <Field label="Seller">{listing.seller_type ?? "—"}</Field>
              <Field label="Source">{listing.source}</Field>
              <Field label="Days listed">
                {daysSince(listing.first_seen_at) ?? "—"}
              </Field>
              <Field label="Last seen">{relTime(listing.last_seen_at)}</Field>
              {marketMedian && (
                <Field label="Market median">{clp(marketMedian)}</Field>
              )}
            </dl>
            <div className="mt-6 flex items-center gap-3">
              <a
                href={listing.url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-block rounded-md border border-neutral-700 px-4 py-2 text-sm font-medium hover:bg-neutral-900"
              >
                Open on {listing.source} ↗
              </a>
              <WatchButton listingId={listing.id as number} initial={watched} />
            </div>
          </div>
        </div>

        {prices.length > 1 && (
          <section className="rounded-lg border border-neutral-800 bg-neutral-950 p-4">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-neutral-400">
              Price history · {prices.length} observations
            </h2>
            <PriceChart data={prices} />
          </section>
        )}
      </main>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wider text-neutral-500">
        {label}
      </dt>
      <dd className="mt-0.5 tabular-nums">{children}</dd>
    </div>
  );
}
