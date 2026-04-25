"use client";

import { useState, useTransition } from "react";
import { createClient } from "@/lib/supabase-browser";
import { Star } from "lucide-react";

export function WatchButton({
  listingId,
  initial,
  variant = "default",
}: {
  listingId: number;
  initial: boolean;
  variant?: "default" | "icon";
}) {
  const [watched, setWatched] = useState(initial);
  const [pending, startTransition] = useTransition();
  const supabase = createClient();

  async function toggle() {
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) return;

    const next = !watched;
    setWatched(next);

    startTransition(async () => {
      if (next) {
        await supabase
          .from("watchlist")
          .upsert({ user_id: user.id, listing_id: listingId })
          .throwOnError();
      } else {
        await supabase
          .from("watchlist")
          .delete()
          .eq("user_id", user.id)
          .eq("listing_id", listingId)
          .throwOnError();
      }
    });
  }

  if (variant === "icon") {
    return (
      <button
        type="button"
        onClick={toggle}
        aria-label={watched ? "Remove from watchlist" : "Add to watchlist"}
        className="p-1 text-neutral-500 hover:text-yellow-400 transition"
        disabled={pending}
      >
        <Star
          className="h-4 w-4"
          fill={watched ? "currentColor" : "none"}
          color={watched ? "#facc15" : "currentColor"}
        />
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={pending}
      className={
        "inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition " +
        (watched
          ? "border-yellow-500 bg-yellow-500/10 text-yellow-300 hover:bg-yellow-500/20"
          : "border-neutral-700 hover:bg-neutral-900")
      }
    >
      <Star
        className="h-4 w-4"
        fill={watched ? "#facc15" : "none"}
        color={watched ? "#facc15" : "currentColor"}
      />
      {watched ? "Watching" : "Watch"}
    </button>
  );
}
