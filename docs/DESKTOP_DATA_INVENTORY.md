# Desktop bundled data inventory

Historical selected-file inventory for an earlier scoped 0.1.0 desktop payload using LCA b3a6b1a79e534add7f86ae3b327c8e576be76b09. This table is not the r4 inventory. For r4, installed resources/runtime/payload-manifest.json is authoritative and pins One 3c2cd79e7d87e9166990c59a9df5a0440182c66e and LCA 958c51b8d58480b32b1f0fa76bdce9c4dbad4941. Paths below are relative to installed resources/runtime. SHA-256 is the file byte hash, not a source-record or licence hash. The payload manifest retains the exact source revisions and full dependency/file inventory.

## Source and permission review

| Asset group | Source and evidence | Redistribution status |
| --- | --- | --- |
| EF3.1 CSVs (one copy) | European Commission/JRC EF3.1 ILCD extraction and 25-indicator reorder; two exact CSV hashes, indicator identities and local display enhancements traced | JRC attribution, transformations and Commission reuse notice recorded in DATA_PROVENANCE.md |
| Selected elementary catalog and tidas_reference_seed | Three original metadata rows with original header; two required unit groups selected at initialization from the reference seed | Historical TianGong database MIT notice retained; JRC attribution preserved; exact selection and hashes retained |
| TianGong grid Process 01.01.014 snapshot | Pinned source record declares copyright false and Free of charge for all users and uses | Declaration retained; applicability to redistribution must be confirmed separately |
| TianGong Flow / FlowProperty / UnitGroup snapshots and engine provider profiles | Exact upstream versions, owner/source declarations and hashes retained | See retained per-version declarations; missing licence field alone does not forbid reuse |
| Steel authored catalog, templates and seeds | Reviewed authored seed structure with retained source descriptors | Application authorship does not extend to embedded third-party records |
| flow_mappings/nebula-flow-mapping-v1 | Runtime manifest and data retained with CC-BY-4.0 LICENSE and Nebula NOTICE | Mapping identifiers only, with attribution and non-endorsement boundary; no commercial LCI inventories or CFs |

Removed from the desktop package: legacy unit XLSX, full elementary/intermediate CSVs, TianGong Process ZIP, duplicate solver-data EF copy, unused 2023 electricity seed and redundant mapping schema/documentation. The required mapping runtime manifest remains intact; NOTICE and LICENSE are also copied to the installed licenses directory. Python/JavaScript dependency notices are separate from data permission.

This describes the previously scoped desktop payload selection, not a licence-driven prohibition on the historical TianGong dataset. The current Docker initialization retains the full original references and Process ZIP. The desktop builder additionally retains the TianGong MIT copyright/licence text and source NOTICE; each installer retains its own exact manifest; later source documentation does not change an existing binary.

See [retained per-version source declarations](RETAINED_SOURCE_DECLARATIONS.md) for owner/source evidence and the concrete remaining attribution gaps. Application Apache-2.0 licensing does not grant rights over all third-party data.

## Exact selected files

| Path | Bytes | SHA-256 |
| --- | ---: | --- |
| `backends/nebula-lca-api/_internal/data/EF3.1/flow_index.csv` | 11140897 | `21f8ea69c6a73b1fbb2a30538911113e9795fbdc3713e61f318624bf9792b0ce` |
| `backends/nebula-lca-api/_internal/data/EF3.1/indicator_index.csv` | 4814 | `fed89fc7d10ae32f71814230e94992c2c91c9d70af1e33076d44aadf05a1b996` |
| `backends/nebula-lca-api/_internal/data/EF3.1/lcia_factors.csv` | 5197433 | `ac319af1b1eca835df6e80783af486875d04543dbc7a326789fa36a72f0193d3` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/ACCEPTANCE.json` | 242 | `3710f55a40992fabf7b3654971c00cdfff32afa6d26b2e6c131f9ea60eb1cada` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/data/elementary-flow-mappings.v1.jsonl` | 3349984 | `131644486ea0da02fc8585d33a292aeadb0be154924d92263e4f394cf6d2a4e8` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/data/intermediate-flow-mappings.v1.jsonl` | 483067 | `9b5c09b084664b24ae7d579fd8df408d011d58408655fae968120e4f0adc6a88` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/data/unit-conversions.v1.json` | 582 | `2fdf6b8c72cf62103dc16bd3b5642f7dff818cf11123646e92c7851d2cd3bd94` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/LICENSE` | 480 | `6c8bf8287474ae3a8791cbd83004190db6b19ed24039f496138d660b567f4462` |
| `backends/nebula-lca-api/_internal/data/flow_mappings/nebula-flow-mapping-v1/MANIFEST.json` | 763 | `d879c7fe9c084404962c6b5af2a71c495d3f47eae07aaf23ed4b404d6367ccd9` |
| `backends/nebula-lca-api/_internal/data/provider_profiles/steel_elementary_catalog.v1.csv` | 621 | `c85c809fe1be23e8c6517f3434d85da432d5647fef567dfade687f96e7f7e6e2` |
| `backends/nebula-lca-api/_internal/data/provider_profiles/steel_elementary_catalog.v1.provenance.json` | 1164 | `85fd86150fd6e14dcd5c1847370ed38d2611bfa03a360937deeac8d5775a5016` |
| `backends/nebula-lca-api/_internal/data/provider_profiles/steel_tiangong_open_flows.v2.json` | 28758 | `ed18b03239d257dd0d9537716577e1ba3e21f99bda99549c2d659000b0ac31b5` |
| `backends/nebula-lca-api/_internal/data/provider_profiles/steel_tiangong_open_references.v1.json` | 11370 | `ce5e47e3c3b5c4b3c65e28363cf190f659046bf9afea53832a53134a973814cd` |
| `backends/nebula-lca-api/_internal/data/Tiangong/tidas_reference_seed.json` | 22994 | `94ac0c4515fe7d2ebfb7f8ec740e3f4cb46887d7cfe97acbb14188ab51e9396a` |
| `backends/nebula-one-api/_internal/nebula_one/resources/application_profiles.json` | 2245 | `7b26da569a413793349ac6140718d09c8472a17f6dc5808c393e1a94dc8ac38b` |
| `backends/nebula-one-api/_internal/nebula_one/resources/model_processing/steel-bf-bof-1.0.0.json` | 2715 | `bdbe97e5679c320b75bd509c59596dff05f1b088ab486fa3994d8022de5422da` |
| `backends/nebula-one-api/_internal/nebula_one/resources/model_processing/steel-bf-bof-additional-co2.json` | 3968 | `ce3d23d89b29e2b61ee707c1eec5ae90d62585b35d95517c1916fafe11006b17` |
| `backends/nebula-one-api/_internal/nebula_one/resources/model_processing/steel-bf-bof-secondary-co2-user-supply.json` | 4451 | `f68c96bceb22d1b85dd132059af37a81267367ca8d9dce257de1d58057711eab` |
| `backends/nebula-one-api/_internal/nebula_one/resources/model_processing/steel-bf-bof-secondary-co2.json` | 4274 | `c761df500be4516cfbe0837fad3cb49da6d2a020161b0aaa7eae998d279e3ef9` |
| `backends/nebula-one-api/_internal/nebula_one/resources/model_processing/steel-bf-bof.json` | 2715 | `53307615ef55ee026269394f4e76427a1c61521889fef4415343289e26bd91f8` |
| `backends/nebula-one-api/_internal/nebula_one/resources/native_background_climate.json` | 1059 | `7e0ba3402a6ac476be609bddd096c56b9a45501e72fd878a54dc3c6fa9c4ecc2` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/cbam-steel-direct-secondary-1.1.2.json` | 16467 | `a4898fc393e17b7d327162ca465dcfe20d5d3699089a306612d10bd7a8a19d97` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/cbam-steel-direct-selector-1.1.3.json` | 16306 | `795412520ed1495256852160c1f1ea9cf19c9d6e3f72a35a1e02c5b63379e7b4` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/cbam-steel-partial-review-1.0.0.json` | 3601 | `102ab37cc14f695851b48b9b1900ab2bd30faf7634ea37122fcef21e52ded575` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/cbam-steel-partial-review-1.0.1.json` | 3626 | `a9ebb579d2d52c94e85ca72b821db1783a3ddaec81e22920325ca6d58a02a2c8` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/cbam-steel-partial-review-1.0.2.json` | 4643 | `7a382ebbc808459abd7cd4526a13a7664b26802b848674c32387a57ecf47dfed` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/cbam-steel-partial-review-1.0.3.json` | 5309 | `18d633fb622f0f6ca118f67b7aa0b827559678e1f114fcc1e1847f1a49147e03` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/cbam-steel-partial-review-1.0.4.json` | 5938 | `21fbe2febdd9536dd0cc65260d95cc0bb1550ababa6b61a7d6b2ae660c53e420` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/ghg-organization-period-model-1.0.1.json` | 3057 | `4873c64e893b0c0e59782405d4a56734df9525bfbf86bba1d022b8d4a034788f` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/ghg-organization-period-model-1.0.2.json` | 3585 | `cfb2324424d078bbb95f19e4b37a9d4ef95da108e79ec2904f8f847a8ebdd909` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/organization-lifecycle-carbon-steel-1.0.0.json` | 4280 | `861fd472f4dd506072eeb65cf2f00fc4d17daed0322286e9d7c5932998e06213` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/organization-lifecycle-carbon-steel-1.0.1.json` | 4280 | `71b6008dec60b4258e17db0bb89cc6868bb72610ca069a43a85447abd9f5135f` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/organization-lifecycle-carbon-steel-1.0.2.json` | 4456 | `39bc3635d0aa8c5e926f0aaf3ff559b85e201ac1a96824345ca8b8ea55719308` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/organization-lifecycle-carbon-steel-1.0.3.json` | 6390 | `293e9ce21f526bc5706300415bbf41d21fead185d1e324da5ee624a9e5f5dc25` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/organization-lifecycle-carbon-steel-1.0.4.json` | 6569 | `8221091926744729f6c2f5a9f54dd6902861c13dc4164e56e472f147162b618d` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/organization-lifecycle-carbon-steel-1.0.5.json` | 7209 | `725104a5ad7e78c2d71d115c7a18866bd65b7f83afbeb6bda1d374e6c6840a94` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/organization-lifecycle-carbon-steel-1.0.6.json` | 7703 | `215fdae005b339974174ce50537348cb8780a1bfe0e4ec2e53c4ee2a668c83bf` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/organization-lifecycle-carbon-steel-1.0.7.json` | 8020 | `fcf3b516fe559dd600ef6a6bc52215986bab9bc6f11119164a8ca3d5ecb36a19` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/pcf-ef31-foreground-1.0.1.json` | 2828 | `a3f0dd2d94f752e8c33654df99f13809873b16f6bd09a196d147d135a62d877f` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/pcf-ef31-foreground-1.0.2.json` | 3204 | `662426f15693ad386f46c1992ca7930bf492304246784e81137372974e1760ad` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/pcf-ef31-foreground-1.0.3.json` | 2989 | `98776027fabde9b6050fcdc78292d259bd828626d30c89d63fb9b18333753f2c` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/pcf-ef31-native-model-boundary-1.0.0.json` | 1811 | `ffe4e8aafa33ed7f54e561caf8df405b2fab5f022d9d25b82683aec6af1e508a` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/pcf-native-model-boundary-1.0.0.json` | 2060 | `f4f4d7c69c92c1ec010f148eb4f5814eea9979d32fceda214d5772baafb8e029` |
| `backends/nebula-one-api/_internal/nebula_one/resources/official_methods/pcf-native-model-boundary-1.0.1.json` | 2060 | `f3813ae3649b9e05413a8e68bd633492c1e77f87e5f66cadb1269341988719a8` |
| `backends/nebula-one-api/_internal/nebula_one/resources/organization_lifecycle_display/steel-1.0.5-en.v1.json` | 1578 | `cad2393c244508b418223c62603ba70e5033e4c0b6fb81895a73c6680c9c4a2d` |
| `backends/nebula-one-api/_internal/nebula_one/resources/organization_lifecycle_display/steel-1.0.6-en.v1.json` | 1688 | `529e6d1c973cb9cb8d9cef41ec0295bb61a6c562c89c78a79fb1962cb5e06f77` |
| `backends/nebula-one-api/_internal/nebula_one/resources/organization_lifecycle_display/steel-1.0.7-en.v1.json` | 1688 | `f789938972cfbc9a5b4a4582640da05488b70990b98cf627d4c7a74a27fa38ed` |
| `backends/nebula-one-api/_internal/nebula_one/resources/product_blueprint.json` | 6231 | `dc3aedb009f6ecbb1970edb76c9a6925036460bec68df0516cda8d544e1d0ba5` |
| `backends/nebula-one-api/_internal/nebula_one/resources/public_supply/tiangong-alternating-current-01.01.003.import.json` | 5349 | `16166e5a86f091a29d8c236d4eb6d6c2f48c280fe800d2eddc2d5a869cc3853e` |
| `backends/nebula-one-api/_internal/nebula_one/resources/public_supply/tiangong-alternating-current-01.01.003.pin.json` | 908 | `d866451b67fab895665391a2a2d062c8fcdc2da4ffad609b7c0682473da60989` |
| `backends/nebula-one-api/_internal/nebula_one/resources/public_supply/tiangong-carbon-dioxide-fossil-03.00.004.import.json` | 4196 | `ec747b3b9d4997f25999adefd9464bc8c592a50f2e116346a4eec31bfab28e08` |
| `backends/nebula-one-api/_internal/nebula_one/resources/public_supply/tiangong-carbon-dioxide-fossil-03.00.004.pin.json` | 805 | `9bbb22d0dbf1eb268a4985afcdbcf81006aa911c17bdf94cb2c4fd018f46b981` |
| `backends/nebula-one-api/_internal/nebula_one/resources/public_supply/tiangong-china-grid-2022.v1.json` | 5181 | `23e9a75d40aa5bbb51293358a32d1b4fc59b6470992f4a9a46a8405d390b1e31` |
| `backends/nebula-one-api/_internal/nebula_one/resources/public_supply/tiangong-grid-2022-01.01.014.snapshot.json` | 30933 | `e2d6f0ffe963575294d158124a3bc8b4059637154908c54b5dedaca43de746fc` |
| `backends/nebula-one-api/_internal/nebula_one/resources/public_supply/tiangong-grid-flows.v2.snapshot.json` | 28758 | `ed18b03239d257dd0d9537716577e1ba3e21f99bda99549c2d659000b0ac31b5` |
| `backends/nebula-one-api/_internal/nebula_one/resources/steel_catalog/steel-flow-prerequisites.v1.json` | 862 | `0e6a1ad28d1849fe586964aa8e64347caac18038bdaea9be49c61de295d6e88d` |
| `backends/nebula-one-api/_internal/nebula_one/resources/steel_catalog/steel-flow-prerequisites.v1.zip` | 1006 | `5b3067d4bba6809be451de5aaf8552a5abd064377b6ea01692d3ab8aea251511` |
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
| `src/nebula_one/resources/public_supply/tiangong-alternating-current-01.01.003.import.json` | 5349 | `16166e5a86f091a29d8c236d4eb6d6c2f48c280fe800d2eddc2d5a869cc3853e` |
| `src/nebula_one/resources/public_supply/tiangong-alternating-current-01.01.003.pin.json` | 908 | `d866451b67fab895665391a2a2d062c8fcdc2da4ffad609b7c0682473da60989` |
| `src/nebula_one/resources/public_supply/tiangong-carbon-dioxide-fossil-03.00.004.import.json` | 4196 | `ec747b3b9d4997f25999adefd9464bc8c592a50f2e116346a4eec31bfab28e08` |
| `src/nebula_one/resources/public_supply/tiangong-carbon-dioxide-fossil-03.00.004.pin.json` | 805 | `9bbb22d0dbf1eb268a4985afcdbcf81006aa911c17bdf94cb2c4fd018f46b981` |
| `src/nebula_one/resources/public_supply/tiangong-china-grid-2022.v1.json` | 5181 | `23e9a75d40aa5bbb51293358a32d1b4fc59b6470992f4a9a46a8405d390b1e31` |
| `src/nebula_one/resources/public_supply/tiangong-grid-2022-01.01.014.snapshot.json` | 30933 | `e2d6f0ffe963575294d158124a3bc8b4059637154908c54b5dedaca43de746fc` |
| `src/nebula_one/resources/public_supply/tiangong-grid-flows.v2.snapshot.json` | 28758 | `ed18b03239d257dd0d9537716577e1ba3e21f99bda99549c2d659000b0ac31b5` |
| `src/nebula_one/resources/steel_catalog/steel-flow-prerequisites.v1.json` | 862 | `0e6a1ad28d1849fe586964aa8e64347caac18038bdaea9be49c61de295d6e88d` |
| `src/nebula_one/resources/steel_catalog/steel-flow-prerequisites.v1.zip` | 1006 | `5b3067d4bba6809be451de5aaf8552a5abd064377b6ea01692d3ab8aea251511` |
