# Bundled reference data and redistribution

The local Compose image builds from Nebula LCA commit `8730ba471b0c329cf5a6033d453ec874d63bc87e`. All reference files named below are tracked at that commit; the build does not read a developer database, local runtime volume, or uncommitted engine file. Nebula One's Apache-2.0 license covers its application code and authored seed structure, not third-party data.

| Asset | Identity | SHA-256 |
| --- | --- | --- |
| Nebula LCA `data/EF3.1/flow_index.csv` | EF 3.1 flow index | `21f8ea69c6a73b1fbb2a30538911113e9795fbdc3713e61f318624bf9792b0ce` |
| Nebula LCA `data/EF3.1/indicator_index.csv` | EF 3.1 indicator index | `fed89fc7d10ae32f71814230e94992c2c91c9d70af1e33076d44aadf05a1b996` |
| Nebula LCA `data/EF3.1/lcia_factors.csv` | EF 3.1 characterization factors | `ac319af1b1eca835df6e80783af486875d04543dbc7a326789fa36a72f0193d3` |
| One `public_supply/tiangong-alternating-current-01.01.003.import.json` | Flow `3d76981f-964a-4865-b588-0e067a2a1163@01.01.003` | `16166e5a86f091a29d8c236d4eb6d6c2f48c280fe800d2eddc2d5a869cc3853e` |
| One `public_supply/tiangong-carbon-dioxide-fossil-03.00.004.import.json` | Flow `08a91e70-3ddc-11dd-923d-0050c2490048@03.00.004` | `ec747b3b9d4997f25999adefd9464bc8c592a50f2e116346a4eec31bfab28e08` |
| One `steel_catalog/steel-flow-prerequisites.v1.zip` | Two authored product Flow catalog rows; original source bundle and selected rows are recorded in the adjacent descriptor | `5b3067d4bba6809be451de5aaf8552a5abd064377b6ea01692d3ab8aea251511` |

The EF 3.1 reference package is documented by the [European Commission JRC](https://eplca.jrc.ec.europa.eu/LCDN/developerEF.xhtml). The two versioned Flow identities come from [TianGong LCA](https://www.tiangong.earth/en). The adjacent `.pin.json` files also record each imported Flow's source record hash, flow property, and unit group. The model's authored electricity supply process is separate from these Flow identities and is not a copy of a TianGong or ecoinvent process inventory.

The Compose image copies the EF 3.1 CSVs because the engine needs all three to resolve exact indicators and flows. These CSVs are method/reference data, not ecoinvent LCI background inventories. Neither this repository nor the local acceptance run establishes a blanket right to redistribute transformed JRC reference files or TianGong records. The [TianGong data guidance](https://www.tiangong.earth/en/methodology) explicitly directs users to check each version's source and licence. Confirm the applicable redistribution terms with the data owners before uploading images or publishing these data files; keep the exact file hashes and attribution with any approved distribution.

Commercial ecoinvent processes, LCI vectors, and licensed provider method packages are absent. A user who has those assets can import them into Nebula LCA separately; a foreground-only steel PCF remains partial until a pinned background solve actually contributes.
