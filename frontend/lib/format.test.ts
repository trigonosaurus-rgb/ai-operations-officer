import { describe, expect, it } from "vitest";

import { citationLabel, formatMs, formatUsd, pdfUrl } from "./format";

describe("format", () => {
  it("shows sub-cent costs with enough digits to be meaningful", () => {
    expect(formatUsd(0.00042)).toBe("$0.0004");
    expect(formatUsd(0.25)).toBe("$0.25");
  });

  it("switches from ms to seconds at one second", () => {
    expect(formatMs(850)).toBe("850 ms");
    expect(formatMs(2140)).toBe("2.1 s");
  });

  it("links citations to the right PDF page", () => {
    expect(pdfUrl("hazmat-policy", 3)).toBe("/api/documents/hazmat-policy.pdf#page=3");
    expect(pdfUrl("hazmat-policy")).toBe("/api/documents/hazmat-policy.pdf");
    expect(citationLabel({ short_title: "Hazmat Policy", page: 3 })).toBe("Hazmat Policy · p.3");
  });
});
