export const NAV = [
  { href: "/", label: "Pick" },
  { href: "/cars", label: "Cars" },
  { href: "/offers", label: "Offers" },
  { href: "/requirements", label: "Requirements" },
  { href: "/data", label: "Data" },
] as const;

/** Map a pathname (trailing slash or not) to the NAV href it belongs to. */
export function activeHref(pathname: string | null): string {
  const p = (pathname ?? "/").replace(/\/+$/, "") || "/";
  if (p === "/") return "/";
  const hit = NAV.filter((n) => n.href !== "/" && p.startsWith(n.href)).sort(
    (a, b) => b.href.length - a.href.length,
  )[0];
  return hit?.href ?? "/";
}
