# Bundled fonts

Both families use the SIL Open Font License 1.1. The app bundles them so it works offline.
Do not sell the fonts alone. Downloaded 2026-11-08.

| Family | Use | Files | Licence |
|---|---|---|---|
| Manrope (variable, weights 400-700) | UI text and headings (MarinaChain product-frame font) | `Manrope-Latin.woff2`, `Manrope-LatinExt.woff2` | `OFL-Manrope.txt` |
| IBM Plex Mono | numbers, station labels, paths, narration | `IBMPlexMono-Regular.woff2`, `IBMPlexMono-Medium.woff2` | `OFL.txt` |

## Sources

**Manrope**: Google Fonts, API version `v23`. The CSS from
`https://fonts.googleapis.com/css2?family=Manrope:wght@400..700&display=swap` names these files:

| File | URL | SHA-256 |
|---|---|---|
| `Manrope-Latin.woff2` (latin subset) | https://fonts.gstatic.com/s/manrope/v23/xn7gYHE41ni1AdIRggexSvfedN4.woff2 | `8bd97e6bbbc1f602a8f791530eed1064c9a357d5731bbc76e3fc587fb068728f` |
| `Manrope-LatinExt.woff2` (latin-ext subset) | https://fonts.gstatic.com/s/manrope/v23/xn7gYHE41ni1AdIRggmxSvfedN62Zw.woff2 | `27eccb1f8944bc26f6511601bac9284786feb5e5bbb0c8035ff09ac63aaf7c52` |

Licence text: https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/OFL.txt

**IBM Plex Mono**: official IBM Plex release `@ibm/plex-mono@2.5.0`, files from
`fonts/complete/woff2/` in
https://github.com/IBM/plex/releases/download/%40ibm/plex-mono%402.5.0/ibm-plex-mono.zip
(zip SHA-256 `6d23f01257663d8cc49a0d64c22ced630b79e0e2a0ac08a0da86e9a38bbc481c`).
Licence text: `LICENSE.txt` of that zip.

`styles.css` declares the `@font-face` rules (unicode ranges as in the Google Fonts CSS).
Overused Grotesk and Satoshi (MarinaChain website fonts) are not bundled: their licence for
the app is not settled.
