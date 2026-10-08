export const NAV = [
  { href: "/", label: "Pick" },
  { href: "/cars", label: "Cars" },
  { href: "/specs", label: "Specs" },
  { href: "/settings", label: "Settings" },
  { href: "/data", label: "Data" },
] as const;

/** Map a pathname (trailing slash or not) to the NAV href it belongs to. */
export function activeHref(pathname: string | null): string {
  const p = (pathname ?? "/").replace(/\/+$/, "") || "/";
  if (p === "/") return "/";
  if (p.startsWith("/offers")) return "/data";
  if (p.startsWith("/requirements")) return "/settings";
  const hit = NAV.filter((n) => n.href !== "/" && p.startsWith(n.href)).sort(
    (a, b) => b.href.length - a.href.length,
  )[0];
  return hit?.href ?? "/";
}
