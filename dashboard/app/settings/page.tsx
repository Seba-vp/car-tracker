import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase-server";
import { Nav } from "@/components/nav";
import { SettingsForm } from "./form";

export const dynamic = "force-dynamic";

async function load() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login?next=/settings");

  const { data } = await supabase
    .from("user_settings")
    .select("telegram_chat_id, updated_at")
    .eq("user_id", user.id)
    .maybeSingle();

  return { telegramChatId: data?.telegram_chat_id ?? null, userEmail: user.email };
}

export default async function Page() {
  const { telegramChatId, userEmail } = await load();
  return (
    <div>
      <Nav pathname="/settings" />
      <main className="mx-auto max-w-3xl space-y-6 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
          <p className="mt-1 text-sm text-neutral-400">
            Signed in as <span className="text-neutral-200">{userEmail}</span>
          </p>
        </header>

        <section className="rounded-lg border border-neutral-800 bg-neutral-950 p-5">
          <h2 className="text-lg font-semibold">Telegram alerts</h2>
          <p className="mt-1 text-sm text-neutral-400">
            Get pinged when a listing matches one of your rules.
          </p>

          <ol className="mt-4 space-y-3 text-sm text-neutral-300">
            <li>
              <span className="text-neutral-500">1.</span> Open Telegram and
              start a chat with the bot ({" "}
              <code className="rounded bg-neutral-900 px-1.5 py-0.5 text-xs">
                @YourCarTrackerBot
              </code>
              ). Send it any message to register.
            </li>
            <li>
              <span className="text-neutral-500">2.</span> Get your chat ID:
              message{" "}
              <a
                href="https://t.me/userinfobot"
                target="_blank"
                rel="noreferrer"
                className="text-blue-400 hover:underline"
              >
                @userinfobot
              </a>{" "}
              and copy the numeric{" "}
              <code className="rounded bg-neutral-900 px-1.5 py-0.5 text-xs">
                Id
              </code>{" "}
              it sends back.
            </li>
            <li>
              <span className="text-neutral-500">3.</span> Paste it below and
              save. Future alert rules you create will deliver to that chat.
            </li>
          </ol>

          <div className="mt-5">
            <SettingsForm initialChatId={telegramChatId ?? ""} />
          </div>

          <p className="mt-4 text-xs text-neutral-500">
            Status:{" "}
            {telegramChatId ? (
              <span className="text-emerald-400">
                connected to chat <code>{telegramChatId}</code>
              </span>
            ) : (
              <span className="text-yellow-400">
                not connected — alerts won't fire until you save a chat ID
              </span>
            )}
          </p>
        </section>
      </main>
    </div>
  );
}
