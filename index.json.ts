// Types for index.json: every published print (one with two or more label photos) and its label photos.
// Usage: import type { Index } from "./index.json.ts"; const index: Index = await (await fetch("index.json")).json();

/** A print's persistent id: its serial (or release) and a name, e.g. "DMG-APSJ-JPN-lisa". */
export type PrintId = string;

/** A label photo's key: the photo's SHA-1, "@", the label's place in it, e.g. "10e0…bb61@71,75". Holds within one build only. */
export type LabelPhotoKey = string;

/** The label shape: Game Boy, Game Boy Color, Game Boy Advance. */
export type Shape = "dmg" | "cgb" | "agb";

export interface Print {
  /** The serial printed on the label, e.g. "DMG-APSJ-JPN"; null when not read. */
  serial: string | null;
  /** Free text telling prints of one serial apart; null when none. */
  tag: string | null;
  /** The release's id in the game database, e.g. "DMG-APSJ"; null when unknown. */
  release: string | null;
  /** The release's game id in the game database; null when unknown. */
  game: string | null;
  /** The family of label photos that look alike (a label photo key). */
  family: string;
  /** The game's title (the database's); null when the release is unknown. */
  title: string | null;
  shape: Shape;
  /** The restored print's image, relative to the site, e.g. "prints/DMG-APSJ-JPN-lisa.avif"; null when it has none. */
  image: string | null;
  /** The image's width and height in pixels; null without an image. */
  size: [width: number, height: number] | null;
  /** Whether the image's paper white was found (else median colours); null without a restore description. */
  paper: boolean | null;
  /** The label photos of this print (keys into Index.label_photos). */
  label_photos: LabelPhotoKey[];
  /** Whether the image is frozen (accepted by hand, not changed by later runs). */
  frozen: boolean;
  /** The label photos the image was restored from; null without a restore description. */
  restored_from: LabelPhotoKey[] | null;
}

export interface LabelPhoto {
  /** The print it belongs to. */
  print: PrintId;
  /** The serial read in this photo; null when none was read. */
  serial: string | null;
  /** Where the photo came from (a source name, e.g. "ebay-search"); null when unknown. */
  source: string | null;
  /** The page the photo was found on. */
  page_url: string | null;
  /** The photo's own URL. */
  image_url: string | null;
  /** A poor fit: listed, but not used to restore the print. */
  poor_fit: boolean;
}

export interface Index {
  prints: Record<PrintId, Print>;
  label_photos: Record<LabelPhotoKey, LabelPhoto>;
}

export default Index;
