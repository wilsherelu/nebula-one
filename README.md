# Nebula One

Nebula One is an Apache-2.0 application for editing versioned production data and reviewing material flows, product climate results, CBAM trials, and organizational lifecycle carbon groups. Nebula LCA owns the model, solver, and LCIA calculation; One calls its public API and stores exact source revisions and result evidence. The interface supports Chinese and English.

This first public candidate includes the steel blast furnace–BOF template and a small electricity supply example with pinned TianGong Flow records. The local engine image includes Nebula LCA's bundled EF 3.1 reference CSVs; it does not contain ecoinvent LCI process inventories or commercial method packages. Users may connect their own licensed background data in Nebula LCA. A foreground-only result is identified as partial; missing factors and missing upstream activities are never counted as zero. Check [data provenance and redistribution terms](docs/DATA_PROVENANCE.md) before publishing the bundled reference data.

## Start the local steel example

Install Docker with Compose. Use a clean Nebula LCA checkout matching `NEBULA_LCA_ENGINE_COMMIT` in `deploy/engine.env`, then set `NEBULA_LCA_SOURCE_DIR` to its absolute path. Verify `git -C <engine-path> rev-parse HEAD` and `git -C <engine-path> status --porcelain` before building. Compose reads this directory; `deploy/engine.env` declares the receipt identity and does not select or verify the source checkout. From this repository root, run:

```sh
docker compose -f deploy/compose.yml -f deploy/compose.steel-demo.local.example.yml up --build -d
```

On Windows PowerShell, set the path for the current shell with `$env:NEBULA_LCA_SOURCE_DIR = 'C:/path/to/nebula-lca'` before running Compose. The default local ports are One `18088`, Nebula LCA API `18081`, and the modeling editor `18082`; set `NEBULA_ONE_PORT`, `NEBULA_LCA_API_PORT`, or `NEBULA_LCA_EDITOR_PORT` to use other free ports. Open `http://127.0.0.1:18088` and check `/api/v1/setup-status` if initialization fails.

The steel startup profile imports only two exact shared product Flow rows needed by the steel model, plus the pinned TianGong Flow versions used by its electricity supply and biosphere ports. It does not import a hydrogen project. The catalog resource records its original source bundle hash and the selected Flow rows; mismatches stop installation. The steel model and method packages keep their own exact versions and content hashes. Restarting the same profile reuses matching catalog and seed records.

The local Compose stack uses separate named volumes. Keep those volumes if you want to retain projects and results. A new installation gets a new database; it does not use any development or demonstration database from another checkout.

## Work with a model

For the Windows local preview, see [desktop installation and data backup](docs/DESKTOP.md) and [candidate release notes and artifact whitelist](docs/RELEASE_CANDIDATE.md). The accepted desktop binary keeps its original source manifest; subsequent release documentation does not replace that binary or its evidence.

The One workbench edits quantities and compatible background associations on a fixed model structure. Structural changes open the Nebula LCA editor; saving there creates an exact new model version that One can import. Results always point to a selected revision and frozen solve, never to `latest`. Product climate and organizational totals include linked background contributions only when the required identity and contribution receipts exist. CBAM output is a trial, not an official declaration.

Accounting schemes are managed inside each template's configuration workspace. Copy an official scheme, select a process and its flows, edit inclusion and reporting groups, then save your own template. New projects inherit independent rules. Before calculating, check and use an exact saved version. Scope and custom categories regroup characterized contributions; exclusion retains the underlying model answer and excluded detail. Closed background networks are attributed to their consuming paths. See [the current standalone trial and acceptance](docs/acceptance/LOCAL_READY_20261015.md).

The custom lifecycle scheme can assign purchased-energy lifecycle contributions to its Scope 2 group. The separate GHG Protocol comparison scheme uses its own generation-only boundary; that requirement does not constrain every custom scheme. Results retain the selected method and its version. See [steel accounting boundaries and corrections](docs/STEEL_SEED_INTERPRETATION.md).

For the architecture and method boundaries, see [Core development logic](docs/CORE_DEVELOPMENT_LOGIC.md), [steel template](docs/STEEL_TEMPLATE.md), [product climate](docs/PCF_PRODUCT_V1.md), and [organizational lifecycle](docs/LC_SCOPE_ORGANIZATION_METHOD.md).

## Develop and test

Python 3.10 or newer and Node.js 22 are supported. Install backend test dependencies with `python -m pip install -e ".[test]"`, run `python -m pytest tests`, then run `npm ci`, `npm run typecheck`, `npm test`, and `npm run build` in `web/`. The public test suite covers the included steel and shared runtime contracts. Some real engine behavior also requires the isolated Docker stack above; unit tests alone do not establish a complete product footprint or CBAM declaration.

For the maintained local workstation, use the primary One and LCA repositories and the existing shared stack at port `18938`; do not start a second stack with the generic example above. See [mainline roots, parked industry material and shared-stack commands](docs/MAINLINE_CONSOLIDATION.md). Unfinished hydrogen and other industry files stay under `drafts/`, outside runtime discovery and packaged resources. Desktop previews remain `0.1.1` until an explicitly authorized GitHub publication.

The API has no public authentication boundary in this local configuration. Keep its published ports on loopback or place it behind a separately configured access layer. Do not place commercial datasets in this repository or its Docker build context.

See [LICENSE](LICENSE) for the application license. Connected data keeps its own source and redistribution terms.
