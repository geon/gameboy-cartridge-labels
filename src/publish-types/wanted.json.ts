// Types for wanted.json: the prints that need a photo or two more to get an image, best chances first.
// Usage: import type { Wanted } from "./wanted.json.ts";

/** A print's persistent id (as in index.json), e.g. "DMG-APSJ-JPN-lisa". */
export type PrintId = string;

/** The label shape: Game Boy, Game Boy Color, Game Boy Advance. */
export type Shape = "dmg" | "cgb" | "agb";

export interface Source {
  /** Where the photo came from (a source name, e.g. "ebay-search"). */
  source?: string | null;
  page_url?: string | null;
  image_url?: string | null;
}

export interface SearchLink {
  /** e.g. "eBay", "Google Images: AGB-AAKJ-JPN". */
  label: string;
  url: string;
}

export interface WantedPrint {
  print: PrintId;
  /** The release's id in the game database, e.g. "AGB-AAKJ". */
  release: string;
  /** The game's title (the database's). */
  title: string;
  system: Shape;
  /** Free text telling prints of one serial apart; null when none. */
  tag: string | null;
  /** The region group, e.g. "JPN", "USA/EUR"; null when unknown. */
  region: string | null;
  /** The print's serial, else the release's serials in its region group. */
  serials: string[];
  /** Label photos still needed. */
  needed: number;
  /** Label photos it has. */
  photos: number;
  /** Whether its label photos agree (same serial read, no tile differing); null for fewer than two. */
  agree: boolean | null;
  /** The lowest resolution among its label photos, pixels per millimetre. */
  px_per_mm: number;
  /** Where its label photos came from, one per label photo. */
  sources: Source[];
  /** Searches that may find more photos. */
  search: SearchLink[];
}

export type Wanted = WantedPrint[];

export default Wanted;
