"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase-browser";
import { relTime } from "@/lib/format";
import type { Rule } from "./page";

const TRIGGER_LABELS: Record<string, string> = {
  below_median: "Below median",
  below_mean: "Below mean",
  price_drop: "Price drop",
};

export function AlertRow({ rule, firedCount }: { rule: Rule; firedCount: number }) {
  const router = useRouter();
  const supabase = createClient();
  const [enabled, setEnabled] = useState(rule.enabled);
  const [pending, startTransition] = useTransition();

  function toggle() {
    const next = !enabled;
    setEnabled(next);
    startTransition(async () => {
      const { error } = await supabase
        .from("alert_rules")
        .update({ enabled: next })
        .eq("id", rule.id);
      if (error) setEnabled(!next);
    });
  }

  function remove() {
    if (!confirm(`Delete rule "${rule.name}"?`)) return;
    startTransition(async () => {
      const { error } = await supabase.from("alert_rules").delete().eq("id", rule.id);
      if (!error) router.refresh();
    });
  }

  const criteria = rule.criteria || {};
  const summary = Object.entries(criteria)
    .filter(([, v]) => v !== null && v !== "" && v !== undefined)
    .map(([k, v]) => `${k}=${v}`)
    .join(" · ") || "any";

  return (
    <tr className="hover:bg-neutral-900/60">
      <td className="px-3 py-2 font-medium">{rule.name}</td>
      <td className="px-3 py-2 text-neutral-400">
        {TRIGGER_LABELS[rule.trigger_type] ?? rule.trigger_type}
      </td>
      <td className="px-3 py-2 text-neutral-500 text-xs">{summary}</td>
      <td className="px-3 py-2 text-right tabular-nums">{rule.threshold_pct}%</td>
      <td className="px-3 py-2 text-right tabular-nums text-neutral-400">
        {firedCount}
      </td>
      <td className="px-3 py-2 text-neutral-500 text-xs">
        {rule.last_evaluated_at ? relTime(rule.last_evaluated_at) : "never"}
      </td>
      <td className="px-3 py-2">
        <button
          onClick={toggle}
          disabled={pending}
          className={
            "rounded px-2 py-0.5 text-xs " +
            (enabled
              ? "bg-emerald-950/60 text-emerald-300 hover:bg-emerald-900/60"
              : "bg-neutral-800 text-neutral-400 hover:bg-neutral-700")
          }
        >
          {enabled ? "enabled" : "disabled"}
        </button>
      </td>
      <td className="px-3 py-2 text-right">
        <button
          onClick={remove}
          disabled={pending}
          className="text-xs text-red-400 hover:text-red-300"
        >
          delete
        </button>
      </td>
    </tr>
  );
}
