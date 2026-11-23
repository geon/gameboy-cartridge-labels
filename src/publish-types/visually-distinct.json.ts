// Types for visually-distinct.json: of each game's prints, the ones that look different enough to browse.
// Every published print with an image is in exactly one of selected and left_out.
// Usage: import type { VisuallyDistinct } from "./visually-distinct.json.ts";

/** A print's persistent id (a key of index.json's prints), e.g. "DMG-APSJ-JPN-lisa". */
export type PrintId = string;

export interface VisuallyDistinct {
  /** The prints to browse: any two of one game differ in 60 % or more of their 2 mm tiles. */
  selected: PrintId[];
  /** Prints left out: each to the selected print of its game it differs least from. */
  left_out: Record<PrintId, PrintId>;
}

export default VisuallyDistinct;
