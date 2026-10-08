import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { compute, usedRoute, type Basis, type DealFields, type Residuals } from "./dealMath";

/** The oracle's numbers (python3 -m model.cost_fixture); both sides check against the same file. */
const FIXTURE = JSON.parse(readFileSync(resolve(process.cwd(), "../tests/fixtures/cost_cases.json"), "utf-8")) as {
  deal_cases: { name: string; basis: Basis; residuals: Residuals; deals: DealFields[]; expected: Record<string, unknown>[] }[];
  used_cases: { name: string; price: number; age_years: number | null; basis: Basis; value_at_end: number | null; expected: Record<string, unknown> }[];
};

/** Python rounds half to even on the binary value; a penny either way is the same figure. */
function expectSame(got: Record<string, unknown>, want: Record<string, unknown>, where: string) {
  for (const [k, v] of Object.entries(want)) {
    const g = got[k];
    const at = `${where}.${k}`;
    if (v == null) { expect(g ?? null, at).toBeNull(); continue; }
    if (typeof v === "number") {
      expect(typeof g, at).toBe("number");
      const tol = Math.abs(v) < 1 ? 1e-4 : 0.011;
      expect(Math.abs((g as number) - v), `${at}: ${g} vs ${v}`).toBeLessThanOrEqual(tol);
    } else if (Array.isArray(v)) expect(g, at).toEqual(v);
    else expect(g, at).toBe(v);
  }
}

describe("dealMath reproduces model/deal_math.py", () => {
  for (const c of FIXTURE.deal_cases) {
    it(c.name, () => {
      const got = compute(c.deals, c.basis, c.residuals) as unknown as Record<string, unknown>[];
      expect(got.length).toBe(c.expected.length);
      c.expected.forEach((want, i) => expectSame(got[i], want, `${c.name}[${i}:${String(want.id)}]`));
    });
  }
  for (const c of FIXTURE.used_cases) {
    it(c.name, () => expectSame(usedRoute(c.price, c.age_years, c.basis, c.value_at_end) as unknown as Record<string, unknown>, c.expected, c.name));
  }
});
