# Windows desktop preview

The Electron application starts the bundled Nebula One and Nebula LCA backends on local loopback addresses. Docker, Python and Node are not required to run the installer. The steel example, template and public reference data are packaged for local calculation. Online catalog searches still require a connection. The bundled TianGong electricity inventory is partial; its contribution does not establish a complete product carbon footprint or regulatory CBAM declaration.

Run the Windows x64 installer and choose a writable installation location. This preview is unsigned. The application keeps databases, import cache and logs under `%APPDATA%/Nebula One`, separate from the installation folder. Close the application before backing up that whole directory. Reinstalling preserves application data; uninstalling also preserves it. Back up before upgrading or manually removing data.

One opens as the main window. Professional modelling uses a separate Nebula LCA window. Saving and returning uses the same exact version and confirmation workflow as the web application. Downloads open the Windows save dialog. Closing the last application window stops the owned local services. Startup errors show the application log directory.

## Build from source

On Windows, prepare Python 3.10, Node and the frontend dependencies in both repositories. Run:

```text
python desktop/build.py --lca-root <Nebula-LCA-checkout> --output <directory-outside-both-repositories>
```

The build creates an isolated Python toolchain, freezes the two existing backends, compiles both web interfaces and generates one NSIS installer. Python dependencies and Electron versions are pinned in `desktop/requirements-build.txt` and `desktop/package-lock.json`. It never reads a developer runtime database. `payload-manifest.json` records individual bundled file hashes and source revisions. Test helpers and build tools are excluded from the installed application.

## Data and licences

Application code is Apache-2.0. Third-party data and dependencies retain their own terms. See [data provenance](DATA_PROVENANCE.md) and the bundled licence notices. Commercial ecoinvent inventories and runtime databases are not packaged. Local functional acceptance and permission to redistribute third-party reference data are separate checks; distribution still requires the licence verification described in the provenance document.
