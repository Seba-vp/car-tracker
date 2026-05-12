"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase-browser";

type Options = { makes: string[]; fuels: string[]; regions: string[] };

export function NewRuleForm({ options }: { options: Options }) {
  const router = useRouter();
  const supabase = createClient();
  const [err, setErr] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  // controlled state
  const [name, setName] = useState("");
  const [triggerType, setTriggerType] = useState("below_median");
  const [thresholdPct, setThresholdPct] = useState(15);
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [yearMin, setYearMin] = useState("");
  const [yearMax, setYearMax] = useState("");
  const [kmMin, setKmMin] = useState("");
  const [kmMax, setKmMax] = useState("");
  const [priceMin, setPriceMin] = useState("");
  const [priceMax, setPriceMax] = useState("");
  const [fuel, setFuel] = useState("");
  const [region, setRegion] = useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (!name.trim()) {
      setErr("Name is required");
      return;
    }
    const criteria: Record<string, string | number> = {};
    if (make) criteria.make = make;
    if (model) criteria.model = model.trim();
    if (yearMin) criteria.yearMin = +yearMin;
    if (yearMax) criteria.yearMax = +yearMax;
    if (kmMin) criteria.kmMin = +kmMin;
    if (kmMax) criteria.kmMax = +kmMax;
    if (priceMin) criteria.priceMin = +priceMin;
    if (priceMax) criteria.priceMax = +priceMax;
    if (fuel) criteria.fuel = fuel;
    if (region) criteria.region = region.trim();

    startTransition(async () => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        setErr("Not signed in");
        return;
      }
      const { error } = await supabase.from("alert_rules").insert({
        user_id: user.id,
        name: name.trim(),
        criteria,
        threshold_pct: thresholdPct,
        trigger_type: triggerType,
        enabled: true,
      });
      if (error) {
        setErr(error.message);
        return;
      }
      router.push("/alerts");
      router.refresh();
    });
  }

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-6 rounded-lg border border-neutral-800 bg-neutral-950 p-5"
    >
      <Section title="Name & trigger">
        <Field label="Name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder='e.g. "Cheap Toyota Corollas 2018+"'
            required
            className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Trigger type">
            <select
              value={triggerType}
              onChange={(e) => setTriggerType(e.target.value)}
              className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
            >
              <option value="below_median">
                Below cohort median (find underpriced)
              </option>
              <option value="below_mean">Below cohort mean</option>
              <option value="price_drop">
                Listing's own price has dropped
              </option>
            </select>
          </Field>
          <Field label="Threshold %">
            <input
              type="number"
              min="1"
              max="90"
              step="1"
              value={thresholdPct}
              onChange={(e) => setThresholdPct(+e.target.value)}
              className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
            />
          </Field>
        </div>
        <p className="text-xs text-neutral-500">
          {triggerType === "price_drop"
            ? `Fires when a listing's price has fallen by ≥${thresholdPct}% from what we first observed.`
            : `Fires when a listing is ≥${thresholdPct}% below the ${triggerType.replace("below_", "")} of the filter cohort.`}
        </p>
      </Section>

      <Section title="Filters (cohort definition)">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          <Field label="Make">
            <select
              value={make}
              onChange={(e) => setMake(e.target.value)}
              className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
            >
              <option value="">Any</option>
              {options.makes.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </Field>
          <Field label="Model contains">
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="e.g. Corolla"
              className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
            />
          </Field>
          <Field label="Region">
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
            >
              <option value="">Any</option>
              {options.regions.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </Field>
          <Field label="Fuel">
            <select
              value={fuel}
              onChange={(e) => setFuel(e.target.value)}
              className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
            >
              <option value="">Any</option>
              {options.fuels.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </Field>
          <Field label="Year min">
            <input
              type="number"
              value={yearMin}
              onChange={(e) => setYearMin(e.target.value)}
              className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
            />
          </Field>
          <Field label="Year max">
            <input
              type="number"
              value={yearMax}
              onChange={(e) => setYearMax(e.target.value)}
              className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
            />
          </Field>
          <Field label="Km min">
            <input
              type="number"
              value={kmMin}
              onChange={(e) => setKmMin(e.target.value)}
              className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
            />
          </Field>
          <Field label="Km max">
            <input
              type="number"
              value={kmMax}
              onChange={(e) => setKmMax(e.target.value)}
              className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
            />
          </Field>
          <Field label="Price min ($)">
            <input
              type="number"
              value={priceMin}
              onChange={(e) => setPriceMin(e.target.value)}
              className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
            />
          </Field>
          <Field label="Price max ($)">
            <input
              type="number"
              value={priceMax}
              onChange={(e) => setPriceMax(e.target.value)}
              className="w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm"
            />
          </Field>
        </div>
      </Section>

      {err && (
        <div className="rounded border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          {err}
        </div>
      )}
      <div className="flex justify-end gap-2">
        <a
          href="/alerts"
          className="rounded-md border border-neutral-700 px-4 py-2 text-sm hover:bg-neutral-900"
        >
          Cancel
        </a>
        <button
          disabled={pending}
          className="rounded-md bg-white px-4 py-2 text-sm font-medium text-black hover:bg-neutral-200 disabled:opacity-50"
        >
          {pending ? "…" : "Create rule"}
        </button>
      </div>
    </form>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-neutral-400">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs uppercase tracking-wider text-neutral-500">
        {label}
      </span>
      {children}
    </label>
  );
}
