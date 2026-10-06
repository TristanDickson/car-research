"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { activeHref, NAV } from "@/lib/nav";

export function Nav() {
  const active = activeHref(usePathname());
  return (
    <nav className="flex gap-5 text-sm font-medium text-gray-400">
      {NAV.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          aria-current={active === item.href ? "page" : undefined}
          className={active === item.href ? "text-gray-100" : "hover:text-gray-100"}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
