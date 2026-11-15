import { describe, expect, it } from "vitest";
import { blankChange, changeErrors, toModification } from "@/lib/scenario-draft";

const change = (patch: Partial<ReturnType<typeof blankChange>>) => ({
  ...blankChange(1),
  ...patch,
});

describe("scenario drafts", () => {
  it.each([
    [{ factor: "0" }, "factor"],
    [{ factor: "101" }, "factor"],
    [{ factor: "abc" }, "factor"],
    [{ factor: "" }, "factor"],
    [{ keys: "load-1, bad key!" }, "keys"],
    [{ type: "set_switch" as const, key: "" }, "key"],
    [{ type: "set_in_service" as const, key: "has space" }, "key"],
  ])("refuse %o", (patch, field) => {
    expect(changeErrors(change(patch))).toHaveProperty(field);
  });

  it("allow a zero factor for generation only", () => {
    expect(changeErrors(change({ type: "scale_generation", factor: "0" }))).toEqual({});
    expect(changeErrors(change({ type: "scale_loads", factor: "0" }))).toHaveProperty("factor");
  });

  it("become modifications", () => {
    expect(toModification(change({ factor: "1.5", keys: "a, b  c" }))).toEqual({
      type: "scale_loads",
      factor: 1.5,
      keys: ["a", "b", "c"],
    });
    expect(toModification(change({ type: "set_switch", key: "s1", flag: true }))).toEqual({
      type: "set_switch",
      key: "s1",
      closed: true,
    });
    expect(
      toModification(change({ type: "scale_generation", factor: "0", controlMode: "" })),
    ).toMatchObject({ keys: null, controlMode: null });
  });
});
