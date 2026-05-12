import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase-server";
import { Nav } from "@/components/nav";
import { relTime } from "@/lib/format";
import { AlertRow } from "./row";

export const dynamic = "force-dynamic";

type Rule = {
  id: number;
  name: string;
  criteria: Record<string, string | number | null>;
  threshold_pct: number;
  trigger_type: string;
  enabled: boolean;
  created_at: string;
  last_evaluated_at: string | null;
};

async function load() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login?next=/alerts");

  const [{ data: rulesData }, { data: settings }] = await Promise.all([
    supabase
      .from("alert_rules")
      .select("*")
      .eq("user_id", user.id)
      .order("created_at", { ascending: false }),
    supabase
      .from("user_settings")
      .select("telegram_chat_id")
      .eq("user_id", user.id)
      .maybeSingle(),
  ]);

  const rules = (rulesData ?? []) as Rule[];
  const ids = rules.map((r) => r.id);
  let notifCountByRule: Record<number, number> = {};
  if (ids.length) {
    const { data: notifs } = await supabase
      .from("alert_notifications")
      .select("rule_id")
      .in("rule_id", ids);
    notifs?.forEach((n: { rule_id: number }) => {
      notifCountByRule[n.rule_id] = (notifCountByRule[n.rule_id] ?? 0) + 1;
    });
  }

  return {
    rules,
    notifCountByRule,
    hasChat: !!settings?.telegram_chat_id,
  };
}

export default async function Page() {
  const { rules, notifCountByRule, hasChat } = await load();

  return (
    <div>
      <Nav pathname="/alerts" />
      <main className="mx-auto max-w-5xl space-y-5 px-6 py-8">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Alert rules</h1>
            <p className="mt-1 text-sm text-neutral-400">
              Get pinged on Telegram when a listing matches.
            </p>
          </div>
          <Link
            href="/alerts/new"
            className="rounded-md bg-white px-4 py-2 text-sm font-medium text-black hover:bg-neutral-200"
          >
            + New rule
          </Link>
        </header>

        {!hasChat && (
          <div className="rounded-md border border-yellow-900 bg-yellow-950/40 px-4 py-3 text-sm text-yellow-200">
            ⚠️ Your Telegram chat ID isn't set — rules will evaluate but no
            messages will be sent. Add it on{" "}
            <Link href="/settings" className="underline">
              /settings
            </Link>
            .
          </div>
        )}

        <div className="overflow-hidden rounded-lg border border-neutral-800">
          <table className="min-w-full divide-y divide-neutral-800 text-sm">
            <thead className="bg-neutral-900 text-xs uppercase tracking-wider text-neutral-400">
              <tr>
                <th className="px-3 py-2 text-left">Name</th>
                <th className="px-3 py-2 text-left">Trigger</th>
                <th className="px-3 py-2 text-left">Criteria</th>
                <th className="px-3 py-2 text-right">Threshold</th>
                <th className="px-3 py-2 text-right">Fired</th>
                <th className="px-3 py-2 text-left">Last evaluated</th>
                <th className="px-3 py-2 text-left">State</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-900 bg-neutral-950">
              {rules.map((r) => (
                <AlertRow
                  key={r.id}
                  rule={r}
                  firedCount={notifCountByRule[r.id] ?? 0}
                />
              ))}
              {rules.length === 0 && (
                <tr>
                  <td
                    colSpan={8}
                    className="px-3 py-10 text-center text-neutral-500"
                  >
                    No rules yet. Click "New rule" to create one.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <p className="text-xs text-neutral-500">
          Rules evaluate after each daily scrape + after the weekly full
          sweep. Each (rule, listing) pair only fires once — you won't get
          spammed with the same car.
        </p>
      </main>
    </div>
  );
}

export type { Rule };
