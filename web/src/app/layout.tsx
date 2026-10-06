import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";
import { Providers } from "./providers";
import { Nav } from "@/components/Nav";
import { SnapshotBanner } from "@/components/SnapshotBanner";

export const metadata: Metadata = {
  title: "car-research",
  description: "Cars, deals and what they actually cost: PCP, PCH and cash on one footing.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-gray-950 text-gray-100 antialiased">
        <Providers>
          <header className="border-b border-gray-800 bg-gray-900">
            <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-4 py-3 sm:px-6">
              <div className="flex min-w-0 items-center gap-5 sm:gap-8">
                <Link href="/" className="shrink-0 text-lg font-semibold tracking-tight text-gray-100">
                  car-research
                </Link>
                <Nav />
              </div>
              <a
                href="https://github.com/TristanDickson/car-research"
                className="text-xs text-gray-500 hover:text-gray-300"
                target="_blank"
                rel="noreferrer"
              >
                repo
              </a>
            </div>
          </header>
          <SnapshotBanner />
          <main id="main" className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6 sm:py-8">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}
