// Types for unknown-serials.json: serial-looking strings read on labels that the game database doesn't know
// (possible new releases, or misreadings), each with the label photos it was read in.
// Usage: import type { UnknownSerials } from "./unknown-serials.json.ts";

/** A label photo's key: the photo's SHA-1, "@", the label's place in it (as in index.json). */
export type LabelPhotoKey = string;

export type UnknownSerials = Record<string, LabelPhotoKey[]>;

export default UnknownSerials;
