// Types for few-photos.json: the open (not frozen) prints with fewer than 3 label photos.
// Usage: import type { FewPhotos } from "./few-photos.json.ts";

/** A print's persistent id, e.g. "DMG-APSJ-JPN-lisa". */
export type PrintId = string;

export type FewPhotos = PrintId[];

export default FewPhotos;
