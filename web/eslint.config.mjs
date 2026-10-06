// Next 16 has no `next lint`; lint runs through the ESLint CLI with flat config.
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

/** @type {import('eslint').Linter.Config[]} */
const config = [
  ...nextCoreWebVitals,
  {
    ignores: ["out/**", ".next/**", "next-env.d.ts"],
  },
];

export default config;
