# Descreen experiments (2026-11-27)

Tried to remove more of the print screen (halftone) from restored prints than src/descreen.py does. Outcome: the user judged the current method best overall after comparing on 10 prints; descreen.py is unchanged. The test scripts lived in a scratchpad folder and were not kept.

## Starting point

AGB-BQZE-USA-mark shows prominent halftoning after descreen. The question was whether the 15 x 15 median used as the background when looking for spectrum peaks is too small to find the screen.

## Findings

- The detection kernel was not the cause. On AGB-BQZE-USA-mark, the 15 x 15 background already finds the four strong screen peaks (2.87 px period, about 177 lpi, two screens at -7.3/82.6 and -37.5/52.6 degrees, 15-21 times their background). 31 x 31 and 61 x 61 raise their ratios and add weak peaks (harmonics near 2 px, side bins), but leave the result practically the same.
- A wider notch alone (NOTCH_SIGMA 0.004 to 0.016 cycles/px) removes the peaks better, but the 1.5 px weighted median afterwards puts screen-frequency energy back; the user saw no improvement. The median helps.
- A patch the user cut out (pure halftone, flat red) is dominated by a second, coarser screen: 5.5 px period (about 92 lpi), peaks at 7.4/-82.6 and -21.6/68.4 degrees. descreen.py never looks for it: MAX_PERIOD is 5 px, and over the whole print the screen only reaches 3-6 times its background (it appears only in some areas), under MIN_RATIO 6.
- Looking for peaks in overlapping 128 px tiles (64 px step, kept if 2+ tiles agree, periods 2-6.5 px) finds the coarse screen on its own (8-11 tiles per peak). Notching those peaks took the patch's 5-6 px pattern from 60 % to 24 % left at NOTCH_SIGMA 0.004, 11 % at 0.016. It looked better but splotchy, and the wide notch rings around edges.
- Ignoring the notch's correction where it is too strong (lightness RMS over a 3 px Gaussian; full under 0.030, none from 0.045; the user's idea, since the screen needs only small corrections and the ringing is stronger) was the best of those variants. In the patch the correction never exceeds 0.034.
- Literature: Xerox patent US 6,839,152 (filed 2000-12-06, expired, fee related, adjusted expiration 2023-06-22) blends a low-pass and a notch-filtered image by local contrast: out = a * low-pass + (1 - a) * notch, a from the 3 x 3 max - min of the low-pass image, 1 at or under A = 8, 0 at or over B = 32. Not read (pages failed): Barney Smith, SPIE 7866 (2011), band-reject filtering in overlapping windows; a Bouman group IEEE TIP paper on edge-preserving descreening.
- The patent as written (Gaussian low-pass 2.2 px, 8/32 read as 0-255) was far too heavy handed: it kept only 58-84 % of the 7-20 px detail. Tuned (low-pass 1.2 px, A/B 3/12 or 1.5/6) it kept 95-98 %. The user preferred the tuned blend over the limited notch ("P 1.2 3/12 on limited").
- Final comparison on 10 prints (DMG-OKJ-nick, AGB-BQZE-USA-mark and 8 random frozen prints) of none, current, and that blend without the median: without the median the blend left more screen than current on 6 of 10 (AGB-AFXP-EUR-tess 89 %, AGB-BQDE-USA-jane 61 % against 58 % and 28 %), while keeping 97-100 % of the 7-20 px detail (current 89-96 %). The user judged the current method better overall.

## Measures used

- Screen left: excess lightness energy (over a 31 x 31 median background of the spectrum before) within 0.01 cycles/px of the tile-found peaks, after divided by before.
- Detail kept: lightness energy at periods 7-20 px, after divided by before.

## If this is picked up again

- The coarse 5.5 px screen is real and current descreen misses it; any fix must find it locally (tiles), not in the whole print's spectrum.
- Keep the median, or replace what it does; dropping it lost most of the gain.
- Untried: notching in local windows (the Barney Smith approach) instead of one global notch.
