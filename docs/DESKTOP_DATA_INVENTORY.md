# Desktop bundled data inventory

Inventory of the accepted 0.1.0 desktop payload (One 44e61ab; LCA d60a893). Paths below are relative to installed resources/runtime. SHA-256 is the file byte hash, not a source-record or licence hash. The payload manifest retains the full dependency/file inventory.

## Source and permission review

| Asset group | Source and evidence | Redistribution status |
| --- | --- | --- |
| EF3.1 CSVs (including solver-data copies) | European Commission JRC EF reference files; exact tracked engine bytes | Transformation and redistribution terms not established by this build; pending review |
| Tiangong legacy bootstrap XLSX, sample CSVs, process ZIP and tidas_reference_seed | Tracked engine bootstrap files; no per-record licence audit completed | Pending review; newer electricity source permission cannot authorize these older assets |
| TianGong grid Process 01.01.014 snapshot | Pinned source record declares copyright false and Free of charge for all users and uses | Declaration retained; applicability to redistribution must be confirmed separately |
| TianGong Flow / FlowProperty / UnitGroup snapshots and engine provider profiles | Exact upstream versions and source hashes retained | Per-version terms require review; public availability alone is not permission |
| china-grid-co2-2023.v1.json | Authored optional model citing the Ministry of Ecology and Environment announcement URL in the file | Source attribution retained; no independent redistribution determination |
| Steel authored catalog, templates and seeds | Reviewed authored seed structure with retained source descriptors | Application authorship does not extend to embedded third-party records |
| flow_mappings/nebula-flow-mapping-v1 | Tracked mapping package selected by the engine public spec | Review its source-derived records independently; no ecoinvent LCI process/vector is included |

The engine spec explicitly selects these assets; One staging also copies the complete public_supply resource directory, so optional unused seed files are still bundled. Python/JavaScript dependency notices are separate from data permission. No blanket data authorization follows from Apache-2.0.

Primary sources: [JRC EF reference package](https://eplca.jrc.ec.europa.eu/LCDN/developerEF.xhtml), [TianGong data reuse guidance](https://www.tiangong.earth/en/methodology). TianGong requires checking each version's source and licence. This audit cannot close the public redistribution gate.

## Exact selected files

| Path | Bytes | SHA-256 |
| --- | ---: | --- |
| `backends/nebula-lca-api/_internal/data/EF3.1/flow_index.csv` | 11140897 | `21f8ea69c6a73b1fbb2a30538911113e9795fbdc3713e61f318624bf9792b0ce` |
| `backends/nebula-lca-api/_internal/data/EF3.1/indicator_index.csv` | 4814 | `fed89fc7d10ae32f71814230e94992c2c91c9d70af1e33076d44aadf05a1b996` |
| `backends/nebula-lca-api/_internal/data/EF3.1/lcia_factors.csv` | 5197433 | `ac319af1b1eca835df6e80783af486875d04543dbc7a326789fa36a72f0193d3` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/ACCEPTANCE.json` | 242 | `3710f55a40992fabf7b3654971c00cdfff32afa6d26b2e6c131f9ea60eb1cada` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/CHANGELOG.md` | 259 | `d0334ecc1fd1b9de60033348547eba8969d1c04d951cd72df78cb3741b894e33` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/data/elementary-flow-mappings.v1.jsonl` | 3349984 | `131644486ea0da02fc8585d33a292aeadb0be154924d92263e4f394cf6d2a4e8` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/data/intermediate-flow-mappings.v1.jsonl` | 483067 | `9b5c09b084664b24ae7d579fd8df408d011d58408655fae968120e4f0adc6a88` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/data/unit-conversions.v1.json` | 582 | `2fdf6b8c72cf62103dc16bd3b5642f7dff818cf11123646e92c7851d2cd3bd94` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/docs/MAPPING_METHOD.md` | 1125 | `9c295e1cd39469fd89d2a333ca2cd69478c292e42ca1ac62d39c78a656f22b37` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/LICENSE` | 480 | `6c8bf8287474ae3a8791cbd83004190db6b19ed24039f496138d660b567f4462` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/MANIFEST.json` | 763 | `d879c7fe9c084404962c6b5af2a71c495d3f47eae07aaf23ed4b404d6367ccd9` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/NOTICE.md` | 781 | `76ee8f9049b59a2cdd945a4f8c3e8ead69237bb256cd4ca0f4a3f7cc60d738df` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/README.md` | 1500 | `9362fb56afb06de7224764250667640dde5864c94c0c403bc14e1f8535859746` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/README.zh-CN.md` | 1358 | `10ce687cf56eac9842c87130cebb6099ea410c87634f88c71237e8cf90ba2c46` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/schema/public-flow-identifier-mapping.v1.schema.json` | 1436 | `778270dfb8c93adb2338ff2a44b74b318887a4675a0feffda0f75b01841b3d91` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/SHA256SUMS` | 1146 | `8e1b85ab7a1f9d861a5940ad99e941dcbae6bc6a1c26f3c45f3a8d517e542644` |
| `backends/nebula-lca-api/_internal/data/provider_profiles/steel_tiangong_open_flows.v2.json` | 28758 | `ed18b03239d257dd0d9537716577e1ba3e21f99bda99549c2d659000b0ac31b5` |
| `backends/nebula-lca-api/_internal/data/provider_profiles/steel_tiangong_open_references.v1.json` | 11370 | `ce5e47e3c3b5c4b3c65e28363cf190f659046bf9afea53832a53134a973814cd` |
| `backends/nebula-lca-api/_internal/data/Tiangong/elementary_flows_sample.csv` | 20243973 | `5d72690c98b7ec120dd598148251479f73f5c3f4f808bd0ee54e28d5ac41fda0` |
| `backends/nebula-lca-api/_internal/data/Tiangong/ILCD_Unit_Groups.xlsx` | 45715 | `576ee3dfb1cf73fc9a37684c6853214bec3a42bf9855e578a52266321034d862` |
| `backends/nebula-lca-api/_internal/data/Tiangong/intermediate_flows_sample.csv` | 499808 | `9231b910c6863a23eca5b937efd19d65927457d2a7c86f7265812c0048db10eb` |
| `backends/nebula-lca-api/_internal/data/Tiangong/tiangong_processes.zip` | 3612348 | `fe5acc26f8a693a6ac221cae284e29972bd366fbe82ca5b50008721469f06222` |
| `backends/nebula-lca-api/_internal/data/Tiangong/tidas_reference_seed.json` | 22994 | `94ac0c4515fe7d2ebfb7f8ec740e3f4cb46887d7cfe97acbb14188ab51e9396a` |
| `backends/nebula-lca-api/_internal/solver-data/EF3.1/flow_index.csv` | 11140897 | `21f8ea69c6a73b1fbb2a30538911113e9795fbdc3713e61f318624bf9792b0ce` |
| `backends/nebula-lca-api/_internal/solver-data/EF3.1/indicator_index.csv` | 4814 | `fed89fc7d10ae32f71814230e94992c2c91c9d70af1e33076d44aadf05a1b996` |
| `backends/nebula-lca-api/_internal/solver-data/EF3.1/lcia_factors.csv` | 5197433 | `ac319af1b1eca835df6e80783af486875d04543dbc7a326789fa36a72f0193d3` |
| `cases/project-templates/steel-bf-bof-inventory/template.json` | 23342 | `8aed5ec78caeb1db7e92a3a26be6c304bfc828a746d5705a8c45e35cc65bb6b1` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/acceptance/expected-values.json` | 21466 | `7cb2352165f53148a9b9919f3504f4983a6352a8e2c3fb7cb7cbd589589668b2` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/boundaries/cbam.json` | 28834 | `1ed9c8eba613d50f5090ec8a3e034280fae0171ea75dfb6ccc4aaafa2d0166f4` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/boundaries/mfa.json` | 16101 | `a4be487b17cefa66a7657c06b8834542184b688c0f7435bde3872723c297ccf2` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/boundaries/pcf.json` | 6324 | `a7aabe3c6020ca9b98294f65fb8bb29b6f4dfe2db42674b101b0c9a100b064e9` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/eu-clause-mapping.json` | 48557 | `78a7a0d1ee83d73f56959bf05ccb28a2c782b5255131bafecbf49bd1edcbaa59` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/eu-clause-mapping.md` | 41655 | `c5d85cc8c3d39e85f4819af50936306c7f59de3859d30cf892a5b0b9daa5e0d6` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/methods/cbam-eu-iron-steel-bf-bof-direct-trial-1.0.1.json` | 14021 | `3b6547e2deda7407c191be356456c51d8392c5e17e6354cc06e2950ea31b2b2d` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/flow-dependencies.json` | 18979 | `fcf9f28bef78c4d87fe953cfdeb8a4302340334f3fb8f9537a74144824d467bc` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/graph.json` | 36956 | `69336d77bb968fc9666cf5a26e2d349b27d09c4b4d8ef26367e269773113febc` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/owned-flows.json` | 12267 | `fac62b13fa53e18fda2dd6d267c70a23c62bd2cc191685fb6910e657aef0bfcf` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/project-row.json` | 1484 | `72b180568e48ce298bee1ed9e4c59fe870b152ce649f674c57cec2d319faa4c1` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/roles.json` | 16942 | `f205a87e6d0aa0971578e84a8199f45d41b2c7bca596f9dd5947e82f08afd0fe` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/parameters/activity-data-slots.json` | 9760 | `fb6738135b7f15028621317f34c6e6a1db2d8529a6a3a7c6c872bdc996136c71` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/parameters/annex-ii-point-g-standard-factors.json` | 8609 | `7fb1b33a8a78b3a335657c27f62e3c92fa92f66eb759453a954934e06cfd9daa` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/parameters/carbon-content.json` | 18557 | `feae25b93e43ebd74259fe34dc941353bb11a636e5f17aa856dde5f6d5eee1a1` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/parameters/sector-specific-declaration-parameters.json` | 5911 | `42b7ba66042e146f7f0b2b1d4527af206b7e10f5f991831f3bc5fd279dafe0f8` |
| `cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/seed.json` | 14668 | `79cdd1771254e76abd8f01a7ada8f9b21481b175445cc59ae4aae1702723cfb3` |
| `src/nebula_one/resources/public_supply/china-grid-co2-2023.v1.json` | 3311 | `3629cc06a3f2276ca312dd3a786e7aa4194dcbb90c30bef97378d2ebfdde142f` |
| `src/nebula_one/resources/public_supply/tiangong-alternating-current-01.01.003.import.json` | 5349 | `16166e5a86f091a29d8c236d4eb6d6c2f48c280fe800d2eddc2d5a869cc3853e` |
| `src/nebula_one/resources/public_supply/tiangong-alternating-current-01.01.003.pin.json` | 908 | `d866451b67fab895665391a2a2d062c8fcdc2da4ffad609b7c0682473da60989` |
| `src/nebula_one/resources/public_supply/tiangong-carbon-dioxide-fossil-03.00.004.import.json` | 4196 | `ec747b3b9d4997f25999adefd9464bc8c592a50f2e116346a4eec31bfab28e08` |
| `src/nebula_one/resources/public_supply/tiangong-carbon-dioxide-fossil-03.00.004.pin.json` | 805 | `9bbb22d0dbf1eb268a4985afcdbcf81006aa911c17bdf94cb2c4fd018f46b981` |
| `src/nebula_one/resources/public_supply/tiangong-china-grid-2022.v1.json` | 5181 | `23e9a75d40aa5bbb51293358a32d1b4fc59b6470992f4a9a46a8405d390b1e31` |
| `src/nebula_one/resources/public_supply/tiangong-grid-2022-01.01.014.snapshot.json` | 30933 | `e2d6f0ffe963575294d158124a3bc8b4059637154908c54b5dedaca43de746fc` |
| `src/nebula_one/resources/public_supply/tiangong-grid-flows.v2.snapshot.json` | 28758 | `ed18b03239d257dd0d9537716577e1ba3e21f99bda99549c2d659000b0ac31b5` |
| `src/nebula_one/resources/steel_catalog/steel-flow-prerequisites.v1.json` | 862 | `0e6a1ad28d1849fe586964aa8e64347caac18038bdaea9be49c61de295d6e88d` |
| `src/nebula_one/resources/steel_catalog/steel-flow-prerequisites.v1.zip` | 1006 | `5b3067d4bba6809be451de5aaf8552a5abd064377b6ea01692d3ab8aea251511` |
