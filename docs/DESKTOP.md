# Windows desktop preview

The Electron application starts the bundled Nebula One and Nebula LCA backends on local loopback addresses. Docker, Python and Node are not required to run the installer. The steel example, template and public reference data are packaged for local calculation. Online catalog searches still require a connection. The bundled TianGong electricity inventory is partial; its contribution does not establish a complete product carbon footprint or regulatory CBAM declaration.

The desktop's built-in elementary metadata directory contains only the three exact Flow identities required by the steel and electricity examples. It is not a complete TianGong directory. Existing fossil CO2 in that directory can be reused in the editor; additional datasets need their own exact imported identities and applicable characterization evidence in Nebula LCA. The legacy TianGong process archive and full Flow CSVs are not included. EF factors and the unit/property reference seed remain available for the bundled examples. The source declarations and mapping attribution notice are included under installed `resources/runtime/licenses`.

Run the Windows x64 installer and choose a writable installation location. This preview is unsigned. The application keeps databases, import cache and logs under `%APPDATA%/nebula-one-desktop`, separate from the installation folder. Close the application before backing up that whole directory. Reinstalling preserves application data; uninstalling also preserves it. Back up before upgrading or manually removing data.

One opens as the main window. Professional modelling opens Nebula LCA in the same native window. Switch with the workspace menu or Ctrl+1 / Ctrl+2; the original One page and drafts stay open. Unsaved LCA edits require a choice before replacing the model or closing the window. Saving and returning uses the same exact version and confirmation workflow as the web application. Downloads open the Windows save dialog. Closing the last application window stops the owned local services. Startup errors show the application log directory.

## Build from source

On Windows, prepare Python 3.10, Node and the frontend dependencies in both repositories. Run:

```text
python desktop/build.py --lca-root <Nebula-LCA-checkout> --output <directory-outside-both-repositories>
```

The build creates an isolated Python toolchain, freezes the two existing backends, compiles both web interfaces and generates one NSIS installer. Python dependencies and Electron versions are pinned in `desktop/requirements-build.txt` and `desktop/package-lock.json`. It never reads a developer runtime database. `payload-manifest.json` records individual bundled file hashes and source revisions. Build tools are excluded from the installed application. The packaged acceptance helper runs only with the explicit --window-smoke flag and an isolated test-data directory.

## Data and licences

Application code is Apache-2.0. Third-party data and dependencies retain their own terms. See [data provenance](DATA_PROVENANCE.md) and the bundled licence notices. Commercial ecoinvent inventories and runtime databases are not packaged. Local functional acceptance and permission to redistribute third-party reference data are separate checks; distribution still requires the licence verification described in the provenance document.
