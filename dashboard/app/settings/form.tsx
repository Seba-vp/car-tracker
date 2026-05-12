"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase-browser";

export function SettingsForm({ initialChatId }: { initialChatId: string }) {
  const router = useRouter();
  const supabase = createClient();
  const [chatId, setChatId] = useState(initialChatId);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    setErr(null);
    startTransition(async () => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        setErr("Not signed in.");
        return;
      }
      const cleaned = chatId.trim();
      const { error } = await supabase
        .from("user_settings")
        .upsert(
          { user_id: user.id, telegram_chat_id: cleaned || null, updated_at: new Date().toISOString() },
          { onConflict: "user_id" },
        );
      if (error) {
        setErr(error.message);
        return;
      }
      setMsg("Saved.");
      router.refresh();
    });
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <label className="text-xs uppercase tracking-wider text-neutral-500">
        Telegram chat ID
      </label>
      <div className="flex gap-2">
        <input
          value={chatId}
          onChange={(e) => setChatId(e.target.value)}
          placeholder="e.g. 123456789"
          inputMode="numeric"
          pattern="-?[0-9]+"
          className="flex-1 rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm"
        />
        <button
          disabled={pending}
          className="rounded-md bg-white px-4 py-2 text-sm font-medium text-black hover:bg-neutral-200 disabled:opacity-50"
        >
          {pending ? "…" : "Save"}
        </button>
      </div>
      {msg && <div className="text-sm text-emerald-400">{msg}</div>}
      {err && <div className="text-sm text-red-400">{err}</div>}
    </form>
  );
}
