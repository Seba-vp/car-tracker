import Link from "next/link";

export function Nav({ pathname }: { pathname: string }) {
  const links = [
    { href: "/", label: "Overview" },
    { href: "/listings", label: "Listings" },
    { href: "/deals", label: "Deals" },
  ];
  return (
    <nav className="flex items-center gap-6 border-b border-neutral-800 px-6 py-3 text-sm">
      <Link href="/" className="font-semibold tracking-tight">
        🚗 car-tracker
      </Link>
      <div className="flex gap-4">
        {links.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={
              pathname === l.href || (l.href !== "/" && pathname.startsWith(l.href))
                ? "text-white"
                : "text-neutral-400 hover:text-white transition"
            }
          >
            {l.label}
          </Link>
        ))}
      </div>
      <form action="/auth/signout" method="post" className="ml-auto">
        <button className="text-xs text-neutral-500 hover:text-white">
          sign out
        </button>
      </form>
    </nav>
  );
}
