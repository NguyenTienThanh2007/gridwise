import { describe, expect, it } from "vitest";
import { centreOn, contains, fitView, panView, viewBox, zoomView } from "@/lib/network/view";

const bounds = { x: 0, y: 0, width: 400, height: 200 };

describe("view", () => {
  it("fits, zooms around the centre within limits, pans and centres", () => {
    const fit = fitView(bounds);
    expect(fit).toEqual(bounds);
    const zoomed = zoomView(fit, 0.5, bounds);
    expect(zoomed).toEqual({ x: 100, y: 50, width: 200, height: 100 });
    expect(zoomView(fit, 0.0001, bounds).width).toBe(40);
    expect(zoomView(fit, 1000, bounds).width).toBe(1600);
    expect(panView(zoomed, 10, -5)).toMatchObject({ x: 90, y: 55 });
    expect(centreOn(zoomed, { x: 0, y: 0 })).toMatchObject({ x: -100, y: -50 });
    expect(contains(zoomed, { x: 150, y: 60 })).toBe(true);
    expect(contains(zoomed, { x: 0, y: 0 })).toBe(false);
    expect(viewBox({ x: 1.234, y: 0, width: 10, height: 5 })).toBe("1.23 0 10 5");
  });
});
