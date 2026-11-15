import { type APIRequestContext, type Locator, type Page, expect } from "@playwright/test";

/**
 * End-to-end tests that write never touch the shared demonstration grid (decision 0014,
 * D4): each copies its topology into its own uniquely named grid through the API, and
 * deletes it afterwards.
 */

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8020";
export const DEMO_GRID_ID = "d0000000-0000-4000-8000-000000000002";

export interface GridCopy {
  id: string;
  name: string;
}

/**
 * One more try after a network error only (for example a keep-alive connection the server
 * closed just as it was reused). Safe for these helpers: reads repeat, and a repeated
 * delete carries If-Match, so it can only be refused, never applied twice. Creating a copy
 * is not retried.
 */
async function once<T>(call: () => Promise<T>): Promise<T> {
  try {
    return await call();
  } catch (error) {
    const network = error instanceof Error && /ECONNRESET|socket hang up/.test(error.message);
    if (!network) throw error;
    return call();
  }
}

export async function copyDemoGrid(request: APIRequestContext, label: string): Promise<GridCopy> {
  const topology = await once(() =>
    request.get(`${API_URL}/api/v1/grids/${DEMO_GRID_ID}/topology`),
  );
  expect(topology.ok()).toBe(true);
  const name = `E2E ${label} ${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const created = await request.post(`${API_URL}/api/v1/grids`, {
    data: {
      name,
      description: "End-to-end test copy of the synthetic demonstration grid. Safe to delete.",
      topology: ((await topology.json()) as { topology: unknown }).topology,
    },
  });
  expect(created.status()).toBe(201);
  return { id: ((await created.json()) as { id: string }).id, name };
}

export async function gridVersion(request: APIRequestContext, id: string): Promise<number | null> {
  const response = await once(() => request.get(`${API_URL}/api/v1/grids/${id}`));
  if (response.status() === 404) return null;
  return ((await response.json()) as { version: number }).version;
}

export async function deleteIfPresent(request: APIRequestContext, id: string): Promise<void> {
  const version = await gridVersion(request, id);
  if (version === null) return;
  await once(() =>
    request.delete(`${API_URL}/api/v1/grids/${id}`, {
      headers: { "If-Match": `"${version}"` },
    }),
  );
}

/** Presses Tab until `target` has the focus: the keyboard path, step by step. */
export async function tabTo(page: Page, target: Locator, limit = 40): Promise<void> {
  for (let step = 0; step < limit; step += 1) {
    if (await target.evaluate((node) => node === document.activeElement)) return;
    await page.keyboard.press("Tab");
  }
  await expect(target).toBeFocused();
}
