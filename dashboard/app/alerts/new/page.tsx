import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase-server";
import { Nav } from "@/components/nav";
import { NewRuleForm } from "./form";

export const dynamic = "force-dynamic";

async function loadOptions() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login?next=/alerts/new");

  const [{ data: makes }, { data: fuels }, { data: regions }] = await Promise.all([
    supabase.from("listings").select("make").is("removed_at", null).not("make", "is", null).limit(5000),
    supabase.from("listings").select("fuel_type").is("removed_at", null).not("fuel_type", "is", null).limit(5000),
    supabase.from("listings").select("region").is("removed_at", null).not("region", "is", null).limit(5000),
  ]);
  const uniq = (arr: { [k: string]: string | null }[] | null, key: string) =>
    Array.from(new Set((arr ?? []).map((r) => r[key]).filter(Boolean))).sort() as string[];
  return {
    makes: uniq(makes, "make"),
    fuels: uniq(fuels, "fuel_type"),
    regions: uniq(regions, "region"),
  };
}

export default async function Page() {
  const options = await loadOptions();
  return (
    <div>
      <Nav pathname="/alerts" />
      <main className="mx-auto max-w-2xl space-y-6 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">New alert rule</h1>
          <p className="mt-1 text-sm text-neutral-400">
            We'll evaluate this after every scrape and ping you on Telegram
            when a matching listing meets the threshold.
          </p>
        </header>
        <NewRuleForm options={options} />
      </main>
    </div>
  );
}
