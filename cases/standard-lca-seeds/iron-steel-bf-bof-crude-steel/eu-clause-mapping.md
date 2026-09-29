# BF-BOF 粗钢标准 seed：欧盟 CBAM 条款映射表

版本 `1.1.0`，起草 2026-09-21。合同与推导口径见 `docs/CBAM_IRON_STEEL_BF_BOF_SEED_V1.md`；本文件是同一张表的 seed 内副本，由 `tmp/segment9h_37_author_steel_clause_mapping.py` 生成，每条引文都在写文件之前按字符偏移回查过缓存正文，回查不过就不写。

范围：CN `7207` 粗钢，路线 `blast_furnace_basic_oxygen_converter`，温室气体只有 `CO2`，商品复杂度 `simple`。监测边界内的过程：ore-sintering、blast-furnace、basic-oxygen-converter、secondary-metallurgy-and-degassing、continuous-casting。

## 1. 来源登记（URL / 条款定位 / 生效 / 抓取 / 内容哈希）

规范化算法：drop script/style blocks, replace remaining tags and character entities with a space, collapse whitespace runs, trim; SHA-256 over UTF-8 bytes。
原因：EUR-Lex HTML embeds a per-request analytics token, so raw byte hashes are not reproducible。
偏移约定：a bare @NNNN offsets into S3, the main source of this seed; every other source carries a prefix, so @s1:NNNN offsets into S1。

| 源 | CELEX | canonical_text_sha256 | 长度 | retrieved_at | 本片用途 |
|---|---|---|---|---|---|
| S1 | 32023R0956 | `65b4b84bc87f4df6bc16fe181e429bb8f5d066ba5a1cb895a0c9c6c58524890b` | 173094 | 2026-09-19 | ST-12 Article 7(1) and the Annex II direct-only listing of Chapter 72; ST-13 and ST-14 Annex I membership of the candidate input codes; the reporting period clause and the default value deferral sentence |
| S3 | 32025R2547 | `7e614b4d284afdde6d4e61b2bcad8fc1ffd1d8318e1c11c6b839cf7f31002680` | 238312 | 2026-09-19 | the whole boundary, functional unit, precursor, activity level and mass balance reading of crude steel, i.e. every clause except ST-12 and ST-14 |

**抓取实况**：2026-09-21 与 2026-09-22 两次复跑结果 `not_retrieved`——all four URLs returned HTTP 202 with an empty body behind an AWS WAF challenge (x-amzn-waf-action: challenge, x-cache: Error from cloudfront); publications.europa.eu timed out from this host and the PDF endpoint was closed by the server. Every record has canonical_text_sha256 null, because an empty body's hash must never be written as if a text had been retrieved. the two hashes in the sources block above remain the 2026-09-19 authoring-time readings and were not re-verified by this attempt; that is gap GS-02 every crude steel boundary, precursor, activity level and mass balance clause used by this seed is in the already cached S3 text, so the failure blocks only the default value numbers, which is modeling gap MG-S05

## 2. 条款表

每条引文都是缓存正文里 `[offset, offset+len)` 区间的逐字切片；生成脚本先比对再落盘，所以这张表不可能与证据漂移。

### ST-01（S3@3867）

- 定位：Recital (6)
- 锚点：The functional units for iron and steel should be determined following the general rule
- 引文：> The functional units for iron and steel should be determined following the general rule, since the CN codes are already allowing differentiation in the calculation of embedded emissions.
- 建模要求：goods_identity: the functional unit is one tonne of the CN code good, here crude steel under CN 7207, with no element-content conversion of any kind. This is the clause that makes the seed's kg-per-tonne constant the only unit bridge in the model
- 必需证据：the recital quoted above plus the general functional unit rule of Article 4(1) that it points at
- 校验：functional_unit.denominator must be a reference product output port of this model and kg_per_tonne must be a declared package constant; no mass floor basis may appear anywhere in the boundary or the package
- 验收用例：a boundary that attaches an element-content denominator to crude steel is refused at build time

### ST-02（S3@50818）

- 定位：Annex I point 2, Table 1, Iron and Steel block
- 锚点：2601 12 00 – Agglomerated iron ores and concentrates, other than roasted iron pyrites Sintered Ore Carbon dioxide
- 引文：> 2601 12 00 – Agglomerated iron ores and concentrates, other than roasted iron pyrites Sintered Ore Carbon dioxide
- 建模要求：goods_identity: the aggregated goods category of the declared good is Crude steel and its greenhouse gas list is CO2 only. The sinter row is quoted in the same block because it fixes which category the in-house sinter belongs to
- 必需证据：the Table 1 rows for the Iron and Steel block, read together with the crude steel row at offset 51389
- 校验：boundaries/cbam.json goods_identity.cn_code, aggregated_goods_category and greenhouse_gases must equal the table reading; the set may not be widened by inference from the route
- 验收用例：a seed that lists nitrous oxide among the counted gases for crude steel is refused

### ST-03（S3@65600）

- 定位：Annex I point 3.11.1, Sintered Ore special provisions
- 锚点：This aggregated goods category includes all kinds of iron ore pellet production (for sale of pellets as well as for direct use in the same installation) and sinter production.
- 引文：> This aggregated goods category includes all kinds of iron ore pellet production (for sale of pellets as well as for direct use in the same installation) and sinter production.
- 建模要求：process_identity: sintering is its own production process with its own system boundary, so the seed models ore-sintering as a separate graph node rather than folding it into the furnace
- 必需证据：the 3.11.1 sentence above plus the 3.11.2 monitoring sentence at offset 65969
- 校验：the sinter node must carry its own carbonate decomposition and solid fuel emission ports; a model that emits all sinter carbon dioxide from the furnace node fails the role coverage check
- 验收用例：removing the sinter carbonate port leaves a mandatory role unanswered and blocks import

### ST-04（S3@67992）

- 定位：Annex I point 3.13.1, Pig Iron special provisions
- 锚点：In integrated steel plants, liquid pig iron (‘hot metal’) directly charged to the oxygen converter is the product which separates the production process for pig iron from the production process of crude steel.
- 引文：> In integrated steel plants, liquid pig iron (‘hot metal’) directly charged to the oxygen converter is the product which separates the production process for pig iron from the production process of crude steel.
- 建模要求：graph_edge_identity: hot metal is the named split stream, so the model must carry one identifiable hot metal exchange from the blast furnace node to the converter node rather than an anonymous bulk transfer
- 必需证据：the 3.13.1 sentence above
- 校验：model/graph.json must contain exactly one hot metal provider/consumer pair, and the CBAM boundary must dispose of both of its ports as internal transfers of the monitored boundary
- 验收用例：a model that names hot metal as a precursor while it is an internal edge of the same monitored boundary is refused by the precursor source gate

### ST-05（S3@68202）

- 定位：Annex I point 3.13.1, third sentence, referring to Article 4(9)
- 锚点：Where the installation does not sell or transfer pig iron to other installations, a joint production process including crude steel can be established making subject to the rules of Article 4.
- 引文：> Where the installation does not sell or transfer pig iron to other installations, a joint production process including crude steel can be established making subject to the rules of Article 4.
- 建模要求：boundary_orientation: a joint production process is permitted, not required. This seed takes the permission and monitors the five processes as one production process boundary, which is the reading that empties the precursor bucket; the alternative reading, where sinter and hot metal each carry their own specific embedded emissions, is registered as modeling gap MG-S02
- 必需证据：the 3.13.1 sentence above plus Article 4(9) at offset 25670, quoted as the joint production rule it invokes
- 校验：consolidation_policy.in_boundary_process_uuids must list every process node of the model, and the two in-house precursor candidates must be disposed of as internal transfers rather than as counted or as precursor mass
- 验收用例：a boundary that lists only some of the model's processes inside the monitored boundary while netting transfers across the omission is refused

### ST-06（S3@71791）

- 定位：Annex I point 3.15.1, crude steel system boundary, hot metal branch
- 锚点：if the process starts from hot metal (liquid pig iron), the system boundary shall include the basic oxygen converter, vacuum degassing, secondary metallurgy, argon oxygen decarburisation / vacuum oxygen decarburisation, continuous casting or ingot casting, where relevant hot-rolling or forging, and all necessary auxiliary activities such as transfers, re-heating, and flue gas cleaning
- 引文：> if the process starts from hot metal (liquid pig iron), the system boundary shall include the basic oxygen converter, vacuum degassing, secondary metallurgy, argon oxygen decarburisation / vacuum oxygen decarburisation, continuous casting or ingot casting, where relevant hot-rolling or forging, and all necessary auxiliary activities such as transfers, re-heating, and flue gas cleaning
- 建模要求：mandatory_role_check: the enumerated activity list is the checklist every crude steel model is measured against. The seed authors converter, secondary metallurgy with degassing and continuous casting as nodes, and carries hot rolling plus flue gas cleaning as declared slots with no exchange, which is modeling gap MG-S09
- 必需证据：the 3.15.1 enumeration above, plus the 3.15.2.1 basic oxygen steelmaking enumeration at offset 72960 and the 3.15.1 sentence at offset 73489 that puts carbon entering in scrap and alloys under a mass balance
- 校验：every activity named by the enumeration must resolve to a node, to a port, or to a slot entry that states it is not authored; an activity that resolves to nothing at all blocks import
- 验收用例：adding a furnace or a caster changes the mandatory role answer set, which the coverage report must restate; a silent omission fails the check

### ST-07（S3@72649）

- 定位：Annex I point 3.15.1, last bullet
- 锚点：only primary hot-rolling and rough shaping by forging to obtain the semi-finished products under CN codes 7207 , 7218 and 7224 are included in this aggregated goods category.
- 引文：> only primary hot-rolling and rough shaping by forging to obtain the semi-finished products under CN codes 7207 , 7218 and 7224 are included in this aggregated goods category. All other rolling and forging processes are included in the aggregated goods category ‘iron or steel products’.
- 建模要求：boundary_extents: the crude steel category ends at the semi-finished product, so finishing rolling is a different aggregated goods category and may not be added to this model to make the numbers look like a plant. The seed's declared good is the continuous casting slab, CN 7207, which the bullet names
- 必需证据：the bullet above plus the 3.16.2 iron or steel products boundary at offset 74694, which is the category the omitted activities belong to
- 校验：model/graph.json must stop at the caster; a node whose technology description is finishing rolling would change the aggregated goods category and is out of scope for this version
- 验收用例：the registered modeling gap MG-S01 keeps the exclusion visible instead of letting it read as a complete steel plant

### ST-08（S3@107951）

- 定位：Annex II point B.3.2, Mass balance method
- 锚点：B.3.2. Mass balance method
- 引文：> B.3.2. Mass balance method
- 建模要求：arithmetic_method: this is the only emission derivation the seed uses. Carbon in, carbon out in product and slag, the difference times f gives the carbon dioxide. Fuels and process materials are treated the same way, which is why the model has no fuel duty, no net calorific value slot and no oxidation factor
- 必需证据：the B.3.2 heading above, plus the method sentence that follows it in the same text, the negative activity rule at offset 108148 and the molar ratio constant at offset 105374
- 校验：parameters/carbon-content.json must state the carbon book per port and the factor as the quoted constant with its offset; the builder must not find any EF times NCV times OF chain in this seed's profile, because the arithmetic_checks block names only mass_balance and result_expectations
- 验收用例：a steel seed that declares the hydrogen seed's combustion check fails the profile gate, which is the intended reading of this clause

### ST-09（S3@235268）

- 定位：Annex IV point 2, sector-specific parameters, Crude steel column
- 锚点：Crude steel — The main reducing agent of the precursor, if known. — Mass % of Mn, Cr, Ni, total of other alloy elements. — Tonnes scrap used for producing 1 t crude steel. — % of scrap that is pre-consumer scrap.
- 引文：> Crude steel — The main reducing agent of the precursor, if known. — Mass % of Mn, Cr, Ni, total of other alloy elements. — Tonnes scrap used for producing 1 t crude steel. — % of scrap that is pre-consumer scrap.
- 建模要求：declaration_fields: the crude steel report asks for four data items and none of them is an emission factor or an element-content denominator. The seed carries them as empty activity slots in parameters/sector-specific-declaration-parameters.json with the reason each one is empty, which is modeling gap MG-S04 for the scrap split
- 必需证据：the Crude steel column above plus the adjacent Sintered Ore column reading N.a. at offset 234898, which is the evidence that no element-content floor exists on this side
- 校验：every one of the four fields must be present with a null value and a stated reason; filling any of them with a plausible default would turn a declaration field into an invented factor
- 验收用例：a package that reads one of these fields as a calculation input is refused because no code path consumes them

### ST-10（S3@68522）

- 定位：Annex I point 3.13.2.1, blast furnace route system boundary
- 锚点：all processes directly or indirectly linked to the production processes emitting CO 2 from fuels and reducing agents such as coke, coke dust, coal, fuel oils, plastic wastes, natural gas, wood wastes, charcoal, as well as from waste gases such as coke oven gas, blast furnace gas or converter gas
- 引文：> all processes directly or indirectly linked to the production processes emitting CO 2 from fuels and reducing agents such as coke, coke dust, coal, fuel oils, plastic wastes, natural gas, wood wastes, charcoal, as well as from waste gases such as coke oven gas, blast furnace gas or converter gas
- 建模要求：source_stream_set: the furnace boundary covers every carbon-bearing input, and the waste gases are named as part of the same system, which is why the model treats furnace gas as an exchange inside the monitored boundary rather than as an emission. Carbon that leaves as exported gas is not subtracted by this version, which is modeling gap MG-S11
- 必需证据：the 3.13.2.1 first bullet above, read with the 3.15.2.1 bullet at offset 73489 that puts scrap and alloy carbon under the same mass balance
- 校验：every carbon-bearing technosphere input of the furnace node must appear in the carbon book of parameters/carbon-content.json with a port, a carbon mass and a destination emission port
- 验收用例：an added fuel input with no carbon book row leaves the book unbalanced and fails the ledger check, which is how a missing emission source is caught rather than lost

### ST-11（S3@183800）

- 定位：Annex II point G, standard factors for installation level direct emissions
- 锚点：G. STANDARD FACTORS USED IN THE MONITORING OF DIRECT EMISSIONS AT INSTALLATION LEVEL
- 引文：> G. STANDARD FACTORS USED IN THE MONITORING OF DIRECT EMISSIONS AT INSTALLATION LEVEL
- 建模要求：factor_source_registry: point G is a numeric table of standard factors, with Table 1 for fuel emission factors and net calorific values, Table 3 for carbonate stoichiometric factors, Table 5 for the iron and steel process material factors and Table 6 for global warming potentials. The seed cites the rows it needs and takes no number from them, because its emissions come from the mass balance of ST-08
- 必需证据：the point G heading above plus the table headings at offsets 186576, 187689 and 188255 and the cited rows recorded in parameters/annex-ii-point-g-standard-factors.json
- 校验：a factor citation must carry annex, section, table number, row label, offset and the source text hash; the builder must find no emission factor literal outside those citation records
- 验收用例：this seed's arithmetic profile binds no combustion check, so a factor cannot leak into a numerator; the citation table is what a later version that models fuel duty would read

### ST-12（S1@72862）

- 定位：Article 7(1)
- 锚点：Embedded emissions in goods shall be calculated pursuant to the methods set out in Annex IV. For goods listed in Annex II only direct emissions shall be calculated and taken into account.
- 引文：> Article 7 Calculation of embedded emissions 1. Embedded emissions in goods shall be calculated pursuant to the methods set out in Annex IV. For goods listed in Annex II only direct emissions shall be calculated and taken into account.
- 建模要求：component_set: crude steel sits in Annex II, so the CBAM result has exactly one component, the direct carbon dioxide term. There is no indirect electricity term and no precursor term, and the ammonia seed's three-component profile must not be copied here
- 必需证据：Article 7(1) above plus the Annex II Iron and steel block at offset 149771 that lists Chapter 72 as a direct-only good
- 校验：the method package must carry formula_graph.calculation actual_specific_embedded_emissions_multi_process_direct_only and must carry no boundary_schema.emission_components block and no mass floor basis; the acceptance ledger must have one emission component row, of kind direct_co2
- 验收用例：adding an indirect electricity component to the crude steel package is refused by the profile gate, not by a review comment

### ST-13（S3@21061）

- 定位：Article 1, definition of precursor
- 锚点：‘precursor’ means any input material into a production process included in the list of goods set out in Annex I to Regulation (EU) 2023/956;
- 引文：> ‘precursor’ means any input material into a production process included in the list of goods set out in Annex I to Regulation (EU) 2023/956;
- 建模要求：membership_test: precursor status is a property of the list, not of the material's role in the process, so the seed tests every input port against Annex I before it considers any attribution. Iron ore concentrates, limestone, coke, coal, natural gas and scrap all fail the test and are inputs with clause-backed exclusions, not precursors
- 必需证据：the definition above plus the Annex I iron and steel cell at S1 offset 144392 that defines the list this good's inputs are tested against
- 校验：boundaries/cbam.json segments.precursors.checked_inputs must carry one row per technosphere input with a three state membership value, and goods_complexity must be derived from those rows rather than written as a constant
- 验收用例：a model that gains an externally purchased ferro-alloy flips the membership reading to listed_precursor, which flips complexity to complex and demands a source pin this repository cannot supply, so the build fails loudly; that path is modeling gap MG-S08

### ST-14（S1@144828）

- 定位：Annex I, Iron and steel cell, exclusion list
- 锚点：7202 99 80 – Other 7204 – Ferrous waste and scrap; remelting scrap ingots and steel Carbon dioxide
- 引文：> 7202 99 80 – Other 7204 – Ferrous waste and scrap; remelting scrap ingots and steel Carbon dioxide
- 建模要求：scrap_membership: heading 7204 appears as one of the entries excluded from the Chapter 72 listing, so ferrous scrap is not a listed good and cannot be a precursor, while 2601 12 00 agglomerated ore is listed in its own right. The seed's scrap input therefore carries carbon through the mass balance and nothing through a precursor rule
- 必需证据：the exclusion list above plus the identical cell in Annex II at S1 offset 150317, plus the count of zero occurrences of 7204 anywhere in the cached S3 text, which is the second independent reading
- 校验：the scrap row in checked_inputs must read not_listed with this clause, and no precursor attribution may attach to it
- 验收用例：a version that treats scrap as a precursor would have to name a source package for scrap, which does not exist and must fail rather than default

### ST-15（S3@180047）

- 定位：Annex II point E, Monitoring of precursors, same production process branch
- 锚点：If the precursors are covered by the same production process in accordance to Article 4(9), only the quantity of additional precursor used and obtained from other installations or from other production processes shall be determined.
- 引文：> If the precursors are covered by the same production process in accordance to Article 4(9), only the quantity of additional precursor used and obtained from other installations or from other production processes shall be determined.
- 建模要求：attribution_order: because this seed monitors its five processes as one production process boundary under ST-05, the in-house sinter and hot metal have no additional quantity to determine, so their carbon dioxide is counted once where it is generated and they are not measured as precursors. The other two branches, offsets 180567 and 180988, are the ones that would apply to externally obtained precursors and are recorded as not exercised
- 必需证据：the branch sentence above plus point E's opening rule at offset 179810, the within-installation and other-installation data set lists at 180567 and 180988, the default value fallback at 182365 and the cross-process attribution field at 180747
- 校验：precursor_rules.sources must be an empty list, and every in-house transfer port must be disposed of as internal_transfer_netted_inside_the_boundary with its graph counterpart named
- 验收用例：a transfer port disposed of as a precursor while both endpoints sit inside the monitored boundary is refused by the double counting gate

### ST-16（S3@183346）

- 定位：Annex II point F, Monitoring of activity levels, off-spec and scrap sentence
- 锚点：Off-spec products, by-products, waste, and scrap produced in a production process, irrespective of whether they are returned to production processes, delivered to other installations, or disposed of, shall not be included in the determination of the activity level. They shall therefore be assigned zero embedded emissions when entering another production process.
- 引文：> Off-spec products, by-products, waste, and scrap produced in a production process, irrespective of whether they are returned to production processes, delivered to other installations, or disposed of, shall not be included in the determination of the activity level. They shall therefore be assigned zero embedded emissions when entering another production process.
- 建模要求：activity_level_and_denominator: the casting crop is produced by a process of this model, so it is neither in the denominator nor a carrier of embedded emissions. The seed authors it as an output port with a not-applicable disposition and no return edge, which is modeling gap MG-S10
- 必需证据：the off-spec sentence above plus the activity level rule at offset 182797 and the double counting sentence at offset 183036
- 校验：exactly one port must be declared the reference product output that carries the functional unit, and every other saleable or discard output outside the counted set must carry a basis; the denominator may not be one of the ports this clause assigns zero to
- 验收用例：a second denominator owner is refused at freeze time with SEED_BOUNDARY_REFERENCE_PROCESS_UNDECLARED

### ST-17（S3@51140）

- 定位：Annex I point 2, Table 1, iron and steel rows around the declared good
- 锚点：7202 1 – Ferro-manganese FeMn Carbon dioxide 7202 4 – Ferro-chromium FeCr Carbon dioxide 7202 6 – Ferro-nickel FeNi Carbon dioxide
- 引文：> 7202 1 – Ferro-manganese FeMn Carbon dioxide 7202 4 – Ferro-chromium FeCr Carbon dioxide 7202 6 – Ferro-nickel FeNi Carbon dioxide
- 建模要求：counter_evidence_for_scrap: Table 1 does give categories and gases for the ferro-alloys that Annex I excludes from Chapter 72, which shows the exclusion of 7204 in ST-14 is a deliberate reading rather than a formatting accident, and that an externally purchased ferro-alloy would be a listed good and therefore a precursor
- 必需证据：the three alloy rows above plus the pig iron and sinter rows at offset 50803 plus the crude steel row at offset 51389, read against the S1 exclusion list of ST-14
- 校验：checked_inputs must state that no listed good enters this model from outside, so goods_complexity stays simple on both the package side and the ledger side
- 验收用例：the moment a listed good is drawn into the model the two sides disagree with a simple reading and the build stops

### ST-18（S3@43777）

- 定位：Annex I point 1 definitions (4), (5), (15), (16) and process emission list
- 锚点：(a) the chemical, electrolytic or pyrometallurgical reduction of metal compounds in ores, concentrates and secondary materials; (b) the removal of impurities from metals and metal compounds; (c) the decomposition of carbonates, including those used for flue gas cleaning;
- 引文：> (a) the chemical, electrolytic or pyrometallurgical reduction of metal compounds in ores, concentrates and secondary materials; (b) the removal of impurities from metals and metal compounds; (c) the decomposition of carbonates, including those used for flue gas cleaning;
- 建模要求：emission_kind_vocabulary: ore reduction and carbonate decomposition are process emissions, not combustion, and carbon monoxide counts as its molar equivalent of carbon dioxide, which is what lets a mass balance ignore oxidation state. The seed labels each counted port with the kind this vocabulary gives it: burden reduction, raceway combustion, carbonate decomposition, converter carbon mass balance and converter flux decomposition
- 必需证据：the three sub bullets above plus definitions (4) at offset 40279, (5) at 40561, (15) at 43253 and (16) at 43483
- 校验：every counted port must carry an emission_kind drawn from this vocabulary and a role id in model/roles.json that states which of the listed processes it belongs to
- 验收用例：a carbonate decomposition port labelled as combustion is a classification error the coverage report exposes, because the basis text and the kind disagree

### ST-19（S3@74114）

- 定位：Annex I point 3.15.2.2, electric arc furnace branch
- 锚点：emitting CO 2 from the consumption of electrodes and electrode pastes;
- 引文：> emitting CO 2 from the consumption of electrodes and electrode pastes;
- 建模要求：scope_of_the_other_route: electrode carbon is a source only in the electric arc furnace branch, so the BF-BOF model carries no electrode port at all. Table 5's scrap rows at offset 188137 belong to the activity data side and do not make scrap a listed good
- 必需证据：the electrode bullet above plus the 3.15.2.2 heading at offset 73705 and the Table 5 iron and steel scrap rows at offset 188137
- 校验：no port, slot or parameter of this seed may name an electrode; the electric arc furnace route is registered as modeling gap MG-S03 instead of being half modelled
- 验收用例：a future version that adds an electrode port must also change the production route and would no longer be this package

任何一条若要改口径（换文本版本、换规范化算法、换偏移），必须升 seed 版本并保留旧引用。

## 3. 已发现缺陷（本轮证据直接指向）

### D-S1

- 事实：the crude steel section sends the reader to point B.3.2 of Annex III at S3 offset 73679, while the number B.3.2 occurs exactly once in the whole text, at offset 107951, inside Annex II; Annex III is divided into A, B and C at offsets 190624, 207277 and 213041 and has no point B.3.2. The neighbouring sections do not agree with each other either: pig iron at offset 67649 cites Annex II, crude steel and iron or steel products cite Annex III
- 后果：a package that quotes the cross-reference literally looks broken next to one that resolves it, and a reader who searches Annex III for the mass balance method finds nothing
- 本片处置：parameters/carbon-content.json records the quoted string, the offset and the resolution sentence together, so the inconsistency is preserved as evidence rather than silently rewritten; modeling gap MG-S07 tracks it

### D-S2

- 事实：the hydrogen seed 1.3.0 ledger row for grid electricity records its Annex I membership under the key listed_in_annex_i, which the builder gate does not read, and the gate returns early when the three state membership key is absent, so a listed good is stored as not listed and nothing notices
- 后果：an incorrect membership claim ships inside a released seed and its boundary text repeats it
- 本片处置：out of scope for this seed, which uses the three state vocabulary; recorded here so the correction has a documented origin, and tracked in docs/STANDARD_SEED_ENTERPRISE_PERIOD_AND_AUTOLOAD_V1.md section 9

### D-S3

- 事实：the build gate accepts an end_use object that states no_runtime_declaration_for_this_good whenever the boundary has no undecided item marked runtime_input_required (seeds/standard_seed_bundle.py lines 1843 to 1866), while the trial itself refuses that same state for every good whose calculation is not the three component one (analysis/cbam_trial_v2.py lines 252 to 259, with the message that a direct only good states its end use as a declaration to collect). For a direct only seed the two are mutually exclusive, so the combination passes the build gate and cannot be solved
- 后果：a direct only seed whose good has no end use provision in the law would ship green and fail on the first trial request, which is the failure mode the acceptance run exists to catch before shipping
- 本片处置：this seed states a declaration to collect instead, which both layers accept, so no runtime behaviour is changed by this slice; the exclusion is recorded here so that a later direct only good with no textual end use provision has a documented origin for choosing between the two layers rather than inventing a provision to satisfy one of them

### D-S4

- 事实：the refusal a declared end use raises is named after one sector: analysis/cbam_trial_v2.py line 875 says that hydrogen consumed inside the reporting installation is not a CBAM good, while the branch that reaches it is the generic check that a declared value sits in the package's not_a_cbam_good list
- 后果：a crude steel filing that declares further_rolling_or_forging is refused with a sentence about hydrogen, so the panel tells the reporter about the wrong good
- 本片处置：left open by this slice because the acceptance run has to observe the refusal as it is today; the fix is to let the message come from the method package's own wording for that value rather than from a literal in the analysis module

## 4. 核实缺口（未验证项，显式声明，不做默认通过）

### GS-01

- 事实：default values for embedded emissions are stated as a rule but not as numbers in either cached text: S1 offset 62837 defers them to implementing acts, S3 offset 182472 defers to Annex IV of the regulation and Annex V at S3 offset 236165 adapts them per region, while the instrument that carries the values was not retrieved. Which implementing act carries them is not verified, so this mapping does not name one
- 后果：every candidate that would be reported on a default value stays undecided, which is modeling gap MG-S05
- 下一步：retrieve the implementing act that publishes the default values, hash it, and attach its table rows to a versioned default value package before any default based result

### GS-02

- 事实：the re-fetch attempts of 2026-09-21 and 2026-09-22 returned HTTP 202 with an empty body behind an AWS WAF challenge for all four URLs, including the two control URLs, so no hash in this file was re-verified after 2026-09-19. The first version of that report recorded the empty body's own SHA-256, which would have read as a successful retrieval; the fetch script now refuses to enter a non-200 response into the evidence chain and the old report is kept as steel_sources_report.pre-fix-20260921.json
- 后果：the cached texts remain authoring-time evidence with a retrieval date, not a live confirmation that the legal text is unchanged
- 下一步：re-run tmp/segment9h_01_eu_fetch_steel.py from a session that clears the challenge and compare hashes before the next seed version bump

### GS-03

- 事实：the atomic weights used by the independent derivation of the carbon book (C 12.011, O 15.999, H 1.008, Fe 55.845, Ca 40.078) were transcribed during authoring without a retrieval, a hash or a captured citation
- 后果：the published factor rows and the atomic derivation agree to within 0.0016 per cent for carbon dioxide and 0.065 per cent for the calcium carbonate residue, but the input constants of the second number have no evidence record, so the seed keeps claim_level demonstration
- 下一步：attach a published source record with URL, retrieval date and content hash in the shape of the Annex II point G record

### GS-04

- 事实：the acceptance engine answers FLOW_PROPERTY_RESOURCE_UNAVAILABLE for every exact-version Flow Property resource, so the electricity flow property the seed pins cannot be re-attested on it, while the mass property resolves
- 后果：the two electricity ports of model/graph.json carry a declared identity that the builder checks for completeness and internal consistency, not one the engine has confirmed
- 下一步：re-probe the catalog resolve route for flow properties on an engine that exposes the resource and flip attestable_on_current_engine to true only with the observed row

### GS-05

- 事实：Annex I membership was tested by searching the candidate CN heading strings in the two cached texts and counting occurrences, not by resolving them against a versioned goods set object, and no chapter-wide comparison of the Section XV and Section VII codes was performed
- 后果：the not_listed readings of ST-13 and ST-14 hold for this seed on that narrower evidence, which is what the checked_inputs limitation row states
- 下一步：publish the Annex I goods list as a versioned package with per code rows and test membership against it

## 5. 建模缺口（不留隐式空洞）

### MG-S01（条款：ST-07）

- 事实：finishing rolling, coating and other iron or steel products processes are outside the model, which ends at the continuous casting slab
- 后果：the model is one crude steel route, not a steel plant, and a reader who expects the product of the whole plant sees a low number
- 下一步：model the 3.16 boundary of S3 offset 74694 as a separate seed rather than as extra nodes here

### MG-S02（条款：ST-05、ST-15）

- 事实：the alternative reading of Article 4(9), where sintered ore and hot metal are treated as within-installation cross-process precursors and each carries its own specific embedded emissions, is not implemented: the precursor source pin must name another seed's released package and the gate refuses a source process belonging to this seed
- 后果：the chosen single boundary reading counts their carbon dioxide once at the process that emits it, which is arithmetically complete but is not the only lawful reading
- 下一步：either publish sintered ore and pig iron as their own seeds, or add an intra-seed precursor source rule to the package contract

### MG-S03（条款：ST-19）

- 事实：the electric arc furnace and direct reduced iron routes are not modelled
- 后果：the production route field is fixed to the blast furnace converter path and the result may not be presented as a route-independent steel figure
- 下一步：a second seed with the 3.15.2.2 boundary, or a multi-route seed once both route parameter sets exist

### MG-S04（条款：ST-09）

- 事实：the pre-consumer share of scrap is a declared field with no value and no attribution rule, so no allocation is performed on scrap
- 后果：scrap carbon enters the mass balance and scrap's upstream burden is outside the boundary; the two are different statements and the boundary file keeps them apart
- 下一步：research the attribution rule before any end-of-life or recycled content claim

### MG-S05（条款：ST-15）

- 事实：the default value route cannot be exercised because the numbers are not in any retrieved text, which is gap GS-01
- 后果：candidates that would be reported on defaults are undecided rather than zero, and the CBAM result refuses while any of them stays open
- 下一步：attach the default value table as a versioned package

### MG-S06（条款：ST-12）

- 事实：the organisation and reporting period leg is not part of this seed; no boundaries/organization-ghg.json is authored for crude steel and no period carbon management package is released with it
- 后果：the same model can serve the three product applications but not an enterprise period inventory, and the CBAM boundary must not be reused as a stand-in for one
- 下一步：add the period layer as a content change, which raises the seed version and keeps the historical reference

### MG-S07（条款：ST-08）

- 事实：the Annex III versus Annex II cross-reference defect D-S1 is documented rather than resolved, and the published carbonate factor 0,440 differs from the atomic residue 0.4397118478108826409288012 by 0.065 per cent
- 后果：two of the eight mass balance residual terms exist only because of that published-versus-atomic difference, so the MFA residual carries them explicitly instead of rounding them away
- 下一步：nothing to resolve in code; the reading is recorded per D-S1

### MG-S08（条款：ST-13、ST-17）

- 事实：no externally purchased listed good enters the model, so the entire external precursor leg is unmodelled: no ferro-alloy, no purchased pig iron, sintered ore or direct reduced iron, and therefore no source identity pin, no default fallback for inconclusive precursor data and no complex goods reading
- 后果：the seed proves the simple good case only, and the acceptance run cannot claim the external precursor refusal path was exercised on real HTTP because no port reaches it
- 下一步：publish at least one ferro-alloy or pig iron seed with a released specific embedded emissions package, then add the port to this model as a version bump

### MG-S09（条款：ST-06、ST-10、ST-18）

- 事实：the material streams that are named by the boundary clauses but authored as slots only: the pre-heated blast air with its oxygen, nitrogen and moisture, the lance oxygen, the ore lattice oxygen that leaves with the furnace gas, the secondary metallurgy protective gas, alloy additions and refractory losses, and the flue gas cleaning reagents including the carbonate that ST-18 counts as a process emission
- 后果：three of the five process nodes close open, and the mass balance residual is explained by eight named terms of which six are exactly these unported oxygen, hydrogen and moisture terms; no closing coefficient is invented
- 下一步：author the air, oxygen and cleaning reagent exchanges when an installation data set exists, which also makes the flue gas carbonate decomposition emission appear

### MG-S10（条款：ST-16）

- 事实：the casting crop leaves the boundary as an output with zero embedded emissions and no return edge, so the model is open-ended on that stream rather than a loop
- 后果：the mass out total includes a stream a real plant re-melts, and the activity level correctly excludes it, which are two different things the boundary files state separately
- 下一步：model the return path together with the activity level rule of ST-16

### MG-S11（条款：ST-10）

- 事实：exported blast furnace, coke oven and converter gas is not an authored stream, so the carbon carried out of the boundary in fuel gas is never subtracted
- 后果：a plant that sells its off-gas shows a lower numerator than this model computes, which biases this seed upward; the slot exists in parameters/activity-data-slots.json with the direction of the bias stated
- 下一步：add the export port and the negative activity row of ST-08's mass balance, then re-derive the carbon book

## 6. 复算方式

```bash
python -B tmp/segment9h_02_check_steel_offsets.py   # 合同文档 79 条引文逐条回查偏移
python -B tmp/segment9h_37_author_steel_clause_mapping.py  # 重生本表，偏移不符即不写文件
PYTHONPATH=src python -B scripts/build_standard_seed_bundle.py \
  --seed cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel --validate-only
```
