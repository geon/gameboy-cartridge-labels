// Types for missing.json: the game database's releases no label photo has, sorted by id.
// Usage: import type { Missing } from "./missing.json.ts";

/** A release's id in the game database, e.g. "AGB-A22J". */
export type ReleaseId = string;

export type Missing = ReleaseId[];

export default Missing;
