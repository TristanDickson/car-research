// Static export only: this app has no server mode. It reads the committed JSON
// snapshot under public/data and runs entirely in the browser (GitHub Pages).
// For the project-subpath host (github.io/<repo>) the deploy workflow sets
// NEXT_PUBLIC_BASE_PATH=/car-research; local dev leaves it empty.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "export",
  // The static export cannot use the Next image optimizer.
  images: { unoptimized: true },
  // Export each route as <route>/index.html so any dumb static server resolves
  // /cars, /deals, ... without extensionless-.html rewrites.
  trailingSlash: true,
  ...(basePath ? { basePath, assetPrefix: basePath } : {}),
};

export default nextConfig;
