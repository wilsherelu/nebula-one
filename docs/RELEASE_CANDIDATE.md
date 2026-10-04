# Windows local preview 0.1.0 (r4 baseline)

Historical evidence: an earlier 0.1.0 preview was independently installed and tested locally: four calculations, modelling in a separate window, saving an exact new version and returning to One, replay, normal exit, restart persistence and replacement installation retaining test data. The rebuilt package with the scoped data directory requires its own installation acceptance; earlier checks do not establish that result. It is unsigned. Clean-machine, strict offline and cross-version upgrade acceptance remain unverified. Partial background coverage remains visible; neither complete PCF nor regulatory CBAM compliance is claimed.

The r4 binary pins One 3c2cd79e7d87e9166990c59a9df5a0440182c66e and LCA 958c51b8d58480b32b1f0fa76bdce9c4dbad4941. It keeps One and LCA in one native window, preserves drafts, and places the sidebar toggle at the navigation edge. Its packaged program was checked from empty isolated data, including four calculations and exact model save/return. The NSIS installer/uninstaller wizard, signing trust prompts and strict offline operation remain unverified. Later documentation commits do not change this binary's source manifest.

The installer is named `Nebula-One-0.1.0-windows-x64.exe`. Its matching `SHA256SUMS.txt` and `RELEASE_NOTES.md` record the binary checksum and exact source revisions; installed `resources/runtime/payload-manifest.json` records the bundled file hashes. Keep these records together. The editor uses root asset URLs to load project deep routes. Desktop initialization imports only the selected example's metadata and precise source versions; legacy process archives and full Flow CSVs are excluded.

## Artifact whitelist

The `public-preview` delivery directory contains only these three files:

- `Nebula-One-0.1.0-windows-x64.exe`
- `SHA256SUMS.txt`
- `RELEASE_NOTES.md`

Do not distribute the surrounding build output directory. Exclude `win-unpacked`, builder metadata/debug files, installations, test databases, runtime reports, evidence and caches. The EXE contains dependency notices, mapping attribution and retained source declarations. Third-party data retains its own licence and attribution; the historical source-tracing limits in [data provenance](DATA_PROVENANCE.md) remain disclosed. A release review must inspect the actual selected assets and their notices; absent record-level licence fields alone are not a prohibition. The [historical inventory](DESKTOP_DATA_INVENTORY.md) does not replace the binary manifest.

## Engine compatibility

The desktop runtime gets its engine identity from the immutable payload manifest and runs its packaged engine. Compose builds the operator's checkout and gets its receipt identity from `deploy/engine.env`; use the exact clean LCA revision recorded in the README. Changing the declaration alone cannot establish compatibility or source identity. The desktop catalog cleanup does not rebuild an existing Web container. Saved results retain their original engine, model version and content hashes.

See [desktop installation, backup and source build](DESKTOP.md). No upload or release has been performed.
