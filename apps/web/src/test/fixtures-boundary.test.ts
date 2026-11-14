import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = path.join(import.meta.dirname, "..");

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const full = path.join(directory, name);
    if (statSync(full).isDirectory()) return name === "test" ? [] : sourceFiles(full);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [full] : [];
  });
}

describe("test fixtures", () => {
  it("are never imported by application code", () => {
    const offenders = sourceFiles(SOURCE).filter((file) =>
      readFileSync(file, "utf8").includes("test/fixtures"),
    );
    expect(offenders).toEqual([]);
  });
});
