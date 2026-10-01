# Windows local preview 0.1.0

This candidate was independently installed and tested locally: four calculations, modelling in a separate window, saving an exact new version and returning to One, replay, normal exit, restart persistence and replacement installation retaining test data. It is unsigned. Clean-machine, strict offline and cross-version upgrade acceptance remain unverified. Partial background coverage remains visible; neither complete PCF nor regulatory CBAM compliance is claimed.

The accepted installer is `Nebula-One-0.1.0-windows-x64.exe`, 178662630 bytes, SHA-256 `51b7ecd6a6f15f801ba2229635de9086b2af5fc295bf83ea353eccea4d058278`. Its payload records One `44e61abbb3ab6fd4eb58fcdf571e0c8112f7f3c8` and Nebula LCA `d60a893d391511ec74bf9e3d248ed05c154b9623`. Later documentation/configuration commits do not describe a newly built installer. The deep-route editor white screen was fixed in this binary and independently retested.

## Artifact whitelist

For the local preview, copy only these three files from the output directory:

- `Nebula-One-0.1.0-windows-x64.exe`
- `SHA256SUMS.txt`
- `RELEASE_NOTES.md`

Do not distribute the whole output directory. Exclude `win-unpacked`, builder metadata/debug files, installations, test databases, runtime reports, evidence and caches. The EXE contains its dependency notices. Public upload remains pending confirmation of the third-party data redistribution terms in [data provenance](DATA_PROVENANCE.md) and the [exact data inventory](DESKTOP_DATA_INVENTORY.md).

## Engine compatibility

The desktop runtime gets its engine identity from the immutable payload manifest and runs its packaged engine. Compose builds the operator's checkout and gets its receipt identity from `deploy/engine.env`. Use the exact clean LCA revision above for this candidate; changing the declaration alone cannot establish compatibility or source identity. No existing Web container was rebuilt for this documentation/configuration correction. Saved results retain their original engine, model version and content hashes.

See [desktop installation, backup and source build](DESKTOP.md). No upload or release has been performed.
