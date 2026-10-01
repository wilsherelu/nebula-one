# Windows local preview 0.1.0

This candidate was independently installed and tested locally: four calculations, modelling in a separate window, saving an exact new version and returning to One, replay, normal exit, restart persistence and replacement installation retaining test data. It is unsigned. Clean-machine, strict offline and cross-version upgrade acceptance remain unverified. Partial background coverage remains visible; neither complete PCF nor regulatory CBAM compliance is claimed.

The installer is named `Nebula-One-0.1.0-windows-x64.exe`. Its matching `SHA256SUMS.txt` and `RELEASE_NOTES.md` record the binary checksum and exact source revisions; installed `resources/runtime/payload-manifest.json` records the bundled file hashes. Keep these records together. The editor uses root asset URLs to load project deep routes. Desktop initialization imports only the selected example's metadata and precise source versions; legacy process archives and full Flow CSVs are excluded.

## Artifact whitelist

The `public-preview` delivery directory contains only these three files:

- `Nebula-One-0.1.0-windows-x64.exe`
- `SHA256SUMS.txt`
- `RELEASE_NOTES.md`

Do not distribute the surrounding build output directory. Exclude `win-unpacked`, builder metadata/debug files, installations, test databases, runtime reports, evidence and caches. The EXE contains dependency notices, mapping attribution and retained source declarations. Public upload remains pending resolution of the concrete reference-data source-chain gaps in [data provenance](DATA_PROVENANCE.md) and the [exact data inventory](DESKTOP_DATA_INVENTORY.md).

## Engine compatibility

The desktop runtime gets its engine identity from the immutable payload manifest and runs its packaged engine. Compose builds the operator's checkout and gets its receipt identity from `deploy/engine.env`; use the exact clean LCA revision recorded in the README. Changing the declaration alone cannot establish compatibility or source identity. The desktop catalog cleanup does not rebuild an existing Web container. Saved results retain their original engine, model version and content hashes.

See [desktop installation, backup and source build](DESKTOP.md). No upload or release has been performed.
