# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.10.0](https://github.com/edalquist/pwrcell_sunspec/compare/v3.9.0...v3.10.0) (2026-11-27)


### Added

* use HA public addon_config for user-accessible files (v3.10.0) ([8f3fa30](https://github.com/edalquist/pwrcell_sunspec/commit/8f3fa302418add8842196ffb6e1cc5a66c56f0bc))

## [3.9.0](https://github.com/edalquist/pwrcell_sunspec/compare/v3.8.0...v3.9.0) (2026-11-27)


### Added

* **beacon:** add offline Beacon SD-card image provisioner (v3.5.0) ([380f8ed](https://github.com/edalquist/pwrcell_sunspec/commit/380f8ed4edc3bc0b4bd9a13c66351ab4f4d58a9d))
* **beacon:** add reusable idempotent local-only Beacon hardening script (v3.4.0) ([0c27cb2](https://github.com/edalquist/pwrcell_sunspec/commit/0c27cb2a7ec220434396933fc6a7b61e9d7f4af6))
* collapsible sub-group rollup rows and wildcard HA rules (v3.3.0) ([9ddea7c](https://github.com/edalquist/pwrcell_sunspec/commit/9ddea7c16aa15c31e21b1859f485d54dc645e795))
* **compare:** rework compare telemetry to verify all grouped registers and flag discrepancies ([acd9ef1](https://github.com/edalquist/pwrcell_sunspec/commit/acd9ef1dc2661e1a7cbdcaf65cadca433f028f58))
* **controls:** support custom bounds on mutable fields for proxy and home assistant ([81cc5ed](https://github.com/edalquist/pwrcell_sunspec/commit/81cc5edc678d5a1beecf7d90ca429c78207a7a03))
* generic SunSpec sub-group support (v3.2.0) ([a6218b6](https://github.com/edalquist/pwrcell_sunspec/commit/a6218b626b2e65b97f541e776012dc1a50d6c5df))
* **grouping:** add export for generalized groupings and telemetry mappings ([862d83f](https://github.com/edalquist/pwrcell_sunspec/commit/862d83f6faea017d6c812e6078b9a892301fae13))
* **ha:** purge stale concept entities, enable all selected sensors, add UI reset/clean actions, bump to 3.0.14 ([1660362](https://github.com/edalquist/pwrcell_sunspec/commit/166036237e81e0d31bb665f7f34dac78f15185b7))
* migrate to v2.0 groupings, enforce strict device isolation, and optimize polling ([3bc2409](https://github.com/edalquist/pwrcell_sunspec/commit/3bc2409df780709605a6cfc83078b69b3491fbbf))
* **mqtt:** deduplicate compound entities, add read/write controls, persistence cleanup, and precision formatting ([83fd473](https://github.com/edalquist/pwrcell_sunspec/commit/83fd473be4f852cc0f18eff416f459a5a24e587d))
* **mqtt:** use add-on unique container hostname as default MQTT client ID, bump version to 3.0.5 ([8010053](https://github.com/edalquist/pwrcell_sunspec/commit/801005317e34c240bc5fb8276798f6c9725485e2))
* **optimizer:** merge inverter output exported energy across MQTT, M102 Wh, and M64207 E ([0b56372](https://github.com/edalquist/pwrcell_sunspec/commit/0b5637250169cc870e125c720917e437f54727b0))
* **optimizer:** unified field grouping, minimal model polling solver, and UI explorer enhancements, bump to 3.0.11 ([7f5bfc8](https://github.com/edalquist/pwrcell_sunspec/commit/7f5bfc85df01f7ade1ed8cbc49d288b73b9c63de))
* **recommender:** add recommendation engine and approval endpoints ([fb6672b](https://github.com/edalquist/pwrcell_sunspec/commit/fb6672bacf44c16f812eb138ed00cb349c990e3c))
* **safety:** unify HA writability on blocked_fields.yaml and add add-on override config (v3.8.0) ([021be22](https://github.com/edalquist/pwrcell_sunspec/commit/021be22af4b0ada84290231c29a501d6d605bbb8))
* strict explicit telemetry grouping, negation handling, and model isolation ([9e80db6](https://github.com/edalquist/pwrcell_sunspec/commit/9e80db663f543a9bfc7fc957b4a44b9ffa3977c6))
* sub-group isolation and rolled-up comparisons and suggestions (v3.2.0) ([063a218](https://github.com/edalquist/pwrcell_sunspec/commit/063a218ad3d768fbc6734fc41cb710306d428ac4))
* **ui,grouping:** add UI options to group, ungroup, and customize field concepts ([43f0a09](https://github.com/edalquist/pwrcell_sunspec/commit/43f0a0977da67953b1a55d39c954e7f42f8fbd5f))
* **ui:** add Export Mappings modal with dual format switcher ([76b4982](https://github.com/edalquist/pwrcell_sunspec/commit/76b4982b54562210bb5d1d87bb8f1ac8cb1d51ca))
* **ui:** add grouping suggestions tab and approval workflow ([9c14fe8](https://github.com/edalquist/pwrcell_sunspec/commit/9c14fe83e213b38854171e29d6ed9301cd658f8d))
* **ui:** add modal and actions to configure field bounds from UI ([8c396e4](https://github.com/edalquist/pwrcell_sunspec/commit/8c396e4e00f364e0ce3e42467b9461fa904d2d2c))
* **ui:** add Modbus and SunSpec register details explorer and bounds restrictions for settable fields, bump to 3.0.10 ([067a18e](https://github.com/edalquist/pwrcell_sunspec/commit/067a18ee46f3c98dbb7a50eceeedde72b302ae8d))
* **ui:** add option to force full device re-scan and clear device cache (v3.1.2) ([2304589](https://github.com/edalquist/pwrcell_sunspec/commit/230458928dca97048e04e1e6802ba4c5cf993e43))
* **ui:** make Web Explorer responsive for mobile and add Playwright desktop/mobile UI tests (v3.6.0) ([3633436](https://github.com/edalquist/pwrcell_sunspec/commit/363343638709bf6e909d41d35f842377099f5751))
* **validation:** add physical plausibility bounds and cumulative energy drop protection, bump to 3.0.7 ([71b9e64](https://github.com/edalquist/pwrcell_sunspec/commit/71b9e64459aca9f20730973522ec30d9e94a1bef))


### Fixed

* **addon:** generate pwrcell.yaml safely via yaml.safe_dump with 0600 permissions ([19ef20c](https://github.com/edalquist/pwrcell_sunspec/commit/19ef20cec8358822d9a4f8ab9f022c1cf43d6185))
* **addon:** set init: false in config.yaml to allow s6-overlay to run as PID 1, bump version to 3.0.2 ([beae950](https://github.com/edalquist/pwrcell_sunspec/commit/beae9506b4a655374e353075bf7fca86f1935ade))
* **beacon:** restore and monitor local MQTT telemetry feed in local-only mode (v3.6.1) ([e453d63](https://github.com/edalquist/pwrcell_sunspec/commit/e453d6356c34fd9b4f3eabc3c1c1efbb2fed3ffe))
* **bridge:** add per-device freshness availability, HA birth republish, and separate poll success tracking ([1e41ca8](https://github.com/edalquist/pwrcell_sunspec/commit/1e41ca823a2b9c57bc8696f2f283024cbf69ad95))
* **bridge:** ignore retained command messages on MQTT command topics ([1478c22](https://github.com/edalquist/pwrcell_sunspec/commit/1478c22b04671927da69308fde6019cebc63db4a))
* **bridge:** import os and only mark _running after start succeeds ([14608bc](https://github.com/edalquist/pwrcell_sunspec/commit/14608bcdff7e69bb799e94f3be7d36cc710fc233))
* **bridge:** return None for invalid/sentinel values in format_state_value and preserve strings ([b73e9f3](https://github.com/edalquist/pwrcell_sunspec/commit/b73e9f3c76f14c350e41342a5e7a75e5aaa6a0c0))
* **bridge:** use single-worker command executor and log listener errors at WARNING ([1977fae](https://github.com/edalquist/pwrcell_sunspec/commit/1977fae35793444ea6eb31700adead248c37d751))
* **catalog:** align JSON model point offsets with XML and prevent repeating subgroup collisions ([42296cf](https://github.com/edalquist/pwrcell_sunspec/commit/42296cf5535fbebdf6aceaa04fa90a2f6d199e17))
* **catalog:** consolidate get_suggested_precision into catalog ([1a6b43e](https://github.com/edalquist/pwrcell_sunspec/commit/1a6b43e2baee2b7d73e8943b6dfaab8ac4f1d5d6))
* **catalog:** deduplicate scale factor point detection into is_scale_factor_point ([29c02b6](https://github.com/edalquist/pwrcell_sunspec/commit/29c02b6b4892f65b8d39a7383c1f064d34f8abd4))
* **catalog:** define named SunSpec model ID constants and resolve control models by name ([ce7fd3c](https://github.com/edalquist/pwrcell_sunspec/commit/ce7fd3c628bac1515c72b8bf7e848eb6ccbbb0f0))
* **ci:** add sanitized test fixtures and fix Release Please config.yaml updater (v3.3.2) ([f2aedee](https://github.com/edalquist/pwrcell_sunspec/commit/f2aedeeb792bc28eaad71df7e1ff2e83896fde4b))
* **client:** classify discovered devices by SunSpec model IDs and skip persisting empty scans ([fc40b69](https://github.com/edalquist/pwrcell_sunspec/commit/fc40b69d1d0306d82e0c3d104cc0d26d705fd2d5))
* **client:** import List in pwrcell.client ([4eacfb6](https://github.com/edalquist/pwrcell_sunspec/commit/4eacfb66a60cd288a332bdffd6fc1897fde0e34f))
* **client:** make mock sim loop interruptible on stop ([f7a4890](https://github.com/edalquist/pwrcell_sunspec/commit/f7a4890821a28e31f84c268919e67ba7ae64054d))
* **client:** revalidate cached device serials against Model 1 and add rescan endpoint ([92d33d2](https://github.com/edalquist/pwrcell_sunspec/commit/92d33d281931c52a663ee834e989af31760d3fb6))
* **cli:** support --log-level both before and after service subcommand, bump version to 3.0.3 ([42d493c](https://github.com/edalquist/pwrcell_sunspec/commit/42d493c9f3960814ef829041056713b40bf08deb))
* **concurrency:** release locks before blocking thread joins, Modbus sync, and MQTT discovery I/O ([8437d73](https://github.com/edalquist/pwrcell_sunspec/commit/8437d73cfe1e6317c89aeb969f316ee1102707f5))
* **concurrency:** synchronize shared state access and replace StateField immutably ([f46f6bc](https://github.com/edalquist/pwrcell_sunspec/commit/f46f6bc5fcb7da1f43dfd8f82dbbda147da84cac))
* **config:** centralize persistent runtime paths under data_dir() ([b17af4f](https://github.com/edalquist/pwrcell_sunspec/commit/b17af4fc7f63556a1b48ffc5cdebc4708b505f56))
* **config:** tolerate null/empty device categories in devices.yaml (v3.5.1) ([f4dadc6](https://github.com/edalquist/pwrcell_sunspec/commit/f4dadc6e82e35a6182d95b2695120c212bc35cff)), closes [#30](https://github.com/edalquist/pwrcell_sunspec/issues/30)
* **config:** type DeviceConfig.read as Optional and fail loudly on malformed AppConfig ([66fd408](https://github.com/edalquist/pwrcell_sunspec/commit/66fd408fbd03fac29a0e1c6172d41db7a1c82e81))
* **controls:** support scaled writable registers and derive HA number bounds from register bounds ([f44cf42](https://github.com/edalquist/pwrcell_sunspec/commit/f44cf42fa813a0d6c232f9ad49c1cadd73127e66))
* **deps:** update alpine docker tag to v3.24 ([#34](https://github.com/edalquist/pwrcell_sunspec/issues/34)) ([7289639](https://github.com/edalquist/pwrcell_sunspec/commit/72896399a1ef6fed6ec1ec4ab6a85ce602cba0b3))
* **deps:** update dependency dataconf to v4 ([d67f222](https://github.com/edalquist/pwrcell_sunspec/commit/d67f222c388c115ef38cdca6d40ba1eecd1a6808))
* **deps:** update dependency dataconf to v4 ([b204d7a](https://github.com/edalquist/pwrcell_sunspec/commit/b204d7a0cd4d8040d4d0fb3c93fd1916e12e4178))
* **deps:** update dependency flask to v3.1.3 [security] ([#28](https://github.com/edalquist/pwrcell_sunspec/issues/28)) ([aa749ef](https://github.com/edalquist/pwrcell_sunspec/commit/aa749efbc3ed4d6471f29b8b404827a2da604182))
* **deps:** update dependency pyyaml to v6.0.4 ([#31](https://github.com/edalquist/pwrcell_sunspec/issues/31)) ([80bc335](https://github.com/edalquist/pwrcell_sunspec/commit/80bc335b5ee7c0fddbc904e4551734da0b574998))
* **deps:** update ghcr.io/home-assistant/base-python docker tag to v3.15 ([#24](https://github.com/edalquist/pwrcell_sunspec/issues/24)) ([cc4ad84](https://github.com/edalquist/pwrcell_sunspec/commit/cc4ad847af86c9899d1d57972bc99e2faf5934c7))
* **deps:** update python non-major dependencies ([#22](https://github.com/edalquist/pwrcell_sunspec/issues/22)) ([503091d](https://github.com/edalquist/pwrcell_sunspec/commit/503091dac192ffceaf8688e8086c390a94ce3de0))
* **ha:** address discovery audit issues and gateway node, bump to 3.0.13 ([a575a22](https://github.com/edalquist/pwrcell_sunspec/commit/a575a22ae97c946a35c5bbc70cd65f83605fc4b4))
* **ha:** export protected and non-writable fields as read-only sensors (v3.6.2) ([242549f](https://github.com/edalquist/pwrcell_sunspec/commit/242549fff4cf2b08834ccb0a641091890a7da776))
* **ha:** handle null or empty selected_fields in ha_config.yaml gracefully ([18d7606](https://github.com/edalquist/pwrcell_sunspec/commit/18d76064294e728e6ee3c8dce66938a14e45e2c6))
* **ha:** preserve full sensor precision and scale-factor display precision (v3.2.2) ([7b99e49](https://github.com/edalquist/pwrcell_sunspec/commit/7b99e49475589a32a1f471d4fe7d31a875654187))
* **ha:** prevent duplicate entities on group selection and fix inverter_state enum mapping (v3.1.6) ([bd11a4c](https://github.com/edalquist/pwrcell_sunspec/commit/bd11a4c6a2496e561a5e5ec1e02499cfcb0478d2))
* **ha:** require yaml, write HA config atomically, and use full serial in object_id ([93507d8](https://github.com/edalquist/pwrcell_sunspec/commit/93507d88ed065df0d6991522a255fc6bd1606eac))
* **ha:** resolve inverter_state enum mapping, deduplicate system_mode options, and retain compound states (v3.1.7) ([16bbc99](https://github.com/edalquist/pwrcell_sunspec/commit/16bbc9935dab2d9c7355ae9b0ede4c9f91c87e7d))
* **ha:** restrict writable discovery exposure to explicit allow-list and exclude SAFETY_SHUTDOWN ([9ace5ff](https://github.com/edalquist/pwrcell_sunspec/commit/9ace5ff9f3e3f70b8dad428435743b52fa55b00b))
* **ha:** seed devices from ha_default_config when ha_config is missing or empty ([bd94f2c](https://github.com/edalquist/pwrcell_sunspec/commit/bd94f2c9caf169753293551e8ef172011d5b1571))
* **lifecycle:** prevent worker resurrection after close, stop bridge on client stop, and handle SIGTERM ([eff3e27](https://github.com/edalquist/pwrcell_sunspec/commit/eff3e2702a3b0396ee5a8bc9f677a2ed54599123))
* **mapping:** query MappingRegistry dynamically instead of import-time caches ([c724fbf](https://github.com/edalquist/pwrcell_sunspec/commit/c724fbff7043ca8ba1de4ff3ed55e169ea99d3ae))
* **modbus:** log duplicate serial at WARNING and assign synthetic serials to blank-SN devices ([5661a95](https://github.com/edalquist/pwrcell_sunspec/commit/5661a95ba1abfbd292480352d12fea62d7f3b8d2))
* **modbus:** retry only transport errors, lower default socket timeout, and bound consecutive scan misses ([4d72736](https://github.com/edalquist/pwrcell_sunspec/commit/4d72736f7fbea3144472751571bed8383505968c))
* **modbus:** skip duplicate serials instead of aborting scan ([7f7259b](https://github.com/edalquist/pwrcell_sunspec/commit/7f7259bc970cd120f9789709edb8674074ef793d))
* **modbus:** treat socket EOF (b'') during drain as disconnect and reconnect immediately ([835d476](https://github.com/edalquist/pwrcell_sunspec/commit/835d476310af4e9b1e1825a7e05d83a97699e95b))
* **modbus:** verify write read-back value and publish clamped device state ([5d0fa5c](https://github.com/edalquist/pwrcell_sunspec/commit/5d0fa5cd65053a7e9423eddcf42c5a03cfd8c06e))
* **models:** pin SSH host keys (TOFU), stage SCP downloads atomically, and warn on sync failure ([377571f](https://github.com/edalquist/pwrcell_sunspec/commit/377571f2e2f1be819d4c7598c856edf59a246ecd))
* **modes:** separate SunSpec SysMd and MQTT proto mode tables and remove broken fallbacks ([6ad8773](https://github.com/edalquist/pwrcell_sunspec/commit/6ad877325b920f73ab63ed17c7684c48e1fd1f6e))
* **mqtt:** do not abort client startup when initial MQTT connect fails ([f08a1f2](https://github.com/edalquist/pwrcell_sunspec/commit/f08a1f254a6c5816a6dc507c87c2eccc2b8c2f8b))
* **mqtt:** format large numbers and energy values without scientific notation ([4cfd35f](https://github.com/edalquist/pwrcell_sunspec/commit/4cfd35f0b8ce593b92355f49e8f0790cf96ea2aa))
* **mqtt:** subscribe narrowly to energy_recordset_live and reconnect only when tunnel port changes ([d978122](https://github.com/edalquist/pwrcell_sunspec/commit/d9781220503a8d771661fe11f7ef70d1402b3d38))
* **optimizer,correlator:** resolve voltage, state, polarity, and energy grouping discrepancies ([f5b496f](https://github.com/edalquist/pwrcell_sunspec/commit/f5b496f22ee7bc199c46e96742976fd116726497))
* **optimizer:** fix swapped TotWhImp and TotWhExp synonyms in CANONICAL_SYNONYMS ([e0e0fbb](https://github.com/edalquist/pwrcell_sunspec/commit/e0e0fbb4cf304b45c22580b2d6d01b0ebf8d6139))
* **optimizer:** normalize %WHRtg unit to % in clean_unit ([b3b39eb](https://github.com/edalquist/pwrcell_sunspec/commit/b3b39eb314a5cefb1c93b5b57ed520c872dc8c0f))
* **poller:** derive DEFAULT_*_MODELS from DEFAULT_*_PATHS ([80dd9a1](https://github.com/edalquist/pwrcell_sunspec/commit/80dd9a1dee04b60f985c1543fd5ab8e730ac148b))
* **poller:** make startup stagger stoppable and simplify tier schedule loop ([40e5ad3](https://github.com/edalquist/pwrcell_sunspec/commit/40e5ad30e9ee1e23c9af0a5969ba8317532612a4))
* **poller:** narrow exception handling and log at debug in safe_point_cvalue ([d9cf5e3](https://github.com/edalquist/pwrcell_sunspec/commit/d9cf5e3cd4d45cf7199b958968531af2942e1c39))
* **poller:** poll all instances of repeating SunSpec models with indexed subgroup keys ([19520cc](https://github.com/edalquist/pwrcell_sunspec/commit/19520cc625ea100a58684e0f4290ce45a9c02dde))
* **poller:** unify subgroup-to-model-ID resolution with exact segment matching ([a2292b7](https://github.com/edalquist/pwrcell_sunspec/commit/a2292b7eb8682ae7265e1f345a2fca037695105d))
* **poller:** validate polling tier in trigger_sync and return 400 on invalid tier ([feb23c7](https://github.com/edalquist/pwrcell_sunspec/commit/feb23c7e407897b1e6c3f9e629bd2ee3c528106f))
* resolve grouping, mqtt discovery, and combined sensor jitter issues (v3.1.5) ([54fa90c](https://github.com/edalquist/pwrcell_sunspec/commit/54fa90c428d76973a15b0cf446762c0728718df2))
* **setup_key:** create SSH private key file with mode 0600 before writing ([f712e42](https://github.com/edalquist/pwrcell_sunspec/commit/f712e42a041857a075ec80db7adce4e1c3e3df5b))
* **setup_key:** handle PermissionError when probing default SSH key paths (v3.3.3) ([39c26e2](https://github.com/edalquist/pwrcell_sunspec/commit/39c26e2147a3be099eb284c3a5176e5688e2aff2))
* **ssh:** add SSH key normalizer to handle single-line/escaped keys, support passphrase & password, bump version to 3.0.4 ([2ce96ca](https://github.com/edalquist/pwrcell_sunspec/commit/2ce96ca5b5ca384a97aca445ca58d2617046b833))
* **state:** drive plausibility bounds from units/device_class, not name substrings ([758c388](https://github.com/edalquist/pwrcell_sunspec/commit/758c388228d641324487fcfbf32d89cc7039d92a))
* **state:** exempt pv_link session energy counters from drop suppression, bump to 3.0.9 ([7e20d4a](https://github.com/edalquist/pwrcell_sunspec/commit/7e20d4a83ab85722ce51c5b61927b6d35c217f25))
* **state:** guard SUNSPEC_SENTINELS membership checks against unhashable values ([fe4a928](https://github.com/edalquist/pwrcell_sunspec/commit/fe4a9282e1c16184dad2e337fe7b49d15483876a))
* **state:** normalize NaN/inf raw_value to None and remove unreachable NaN branch ([7ac9576](https://github.com/edalquist/pwrcell_sunspec/commit/7ac95767f35cc4d9d9834306286e4380f6021bc5))
* **state:** publish zero voltage, inverter state, and battery power limits from MQTT ([14cc721](https://github.com/edalquist/pwrcell_sunspec/commit/14cc721552d003c8e7ffdc7a618c74e8261e1e6c))
* **state:** remove home-grown scale factor cases in update_from_modbus_points ([939f48b](https://github.com/edalquist/pwrcell_sunspec/commit/939f48bf8e10a5234e6d20b4577130943acd748e))
* **state:** replace permanent monotonic counter latch with N-consecutive confirmation ([4cbd453](https://github.com/edalquist/pwrcell_sunspec/commit/4cbd4538f667c128f2cce92e75614564dd3f9cdb))
* **state:** suppress out-of-bounds warning log-spam and handle vendor pseudo-sentinels (v3.2.1, fixes [#15](https://github.com/edalquist/pwrcell_sunspec/issues/15)) ([d4bd31a](https://github.com/edalquist/pwrcell_sunspec/commit/d4bd31ae1031c815de07ab6b0ab1964c9cb06057))
* **sunspec:** evaluate sentinels by register type at raw level only ([45653fb](https://github.com/edalquist/pwrcell_sunspec/commit/45653fb23728e7b31a210b5fd4b605aeadc2554b))
* **sunspec:** resolve math range error and scale factor sentinel corruption, bump to 3.0.6 ([885a6cd](https://github.com/edalquist/pwrcell_sunspec/commit/885a6cda8a9c28cb3018b21997b52e1758264c01))
* **ui,recommender:** exclude scale factor registers from merging UI and suggestions ([d9febe1](https://github.com/edalquist/pwrcell_sunspec/commit/d9febe1f1b79929e1d137d42a5ae0e8fedca11ce))
* **ui:** dynamically display package version instead of hardcoded v3.0 (v3.2.0) ([7d11a80](https://github.com/edalquist/pwrcell_sunspec/commit/7d11a801f0e77fb9bda9be83b1ea7930d5094c67))
* **ui:** remove stray syntax tokens in app.js breaking client execution ([4dad7c7](https://github.com/edalquist/pwrcell_sunspec/commit/4dad7c7c41f89b46dd61d352e615fc0b5ed24280))
* **ui:** use selectDevice instead of fetchDeviceFields after grouping change ([d6cb407](https://github.com/edalquist/pwrcell_sunspec/commit/d6cb4070e7d32592578f51cc01e3911bc5886b36))
* **ui:** use SUNSPEC_SYS_MD_NAMES instead of inverted OPERATING_MODES dict ([10ffaf8](https://github.com/edalquist/pwrcell_sunspec/commit/10ffaf8e88ffff1ff643f1aeb67479f2cb07c683))
* **upgrade:** reconcile persisted groupings, separate AC/DC energy, and restore PV Link primary defaults (v3.2.0) ([0bc3d9f](https://github.com/edalquist/pwrcell_sunspec/commit/0bc3d9ffdff2e5023288462d6255dd2d5078f478))
* **validation:** calibrate plausibility bounds for commercial ratings, bump to 3.0.8 ([bf0ed9d](https://github.com/edalquist/pwrcell_sunspec/commit/bf0ed9dfd49216ce0d12d22ad6455ea22b342f07))
* **version:** derive HA ORIGIN_INFO sw_version from __version__ and align config.yaml ([44f8b25](https://github.com/edalquist/pwrcell_sunspec/commit/44f8b25cfef0a7291fd040baf97f2855bdb41c89))


### Changed

* **catalog,optimizer:** externalize fallback point abbreviations and optimizer preferences to YAML ([5c5f776](https://github.com/edalquist/pwrcell_sunspec/commit/5c5f776b4b90e270dc11ca607a9242d92f059aa9))
* **controls:** derive system operating modes and symbols dynamically from SunSpec metamodels ([5440dff](https://github.com/edalquist/pwrcell_sunspec/commit/5440dfff2dfb9b3048a020a147256641a2c33227))
* **devices:** externalize device types, model classification rules, and tier paths to YAML configs ([610bd99](https://github.com/edalquist/pwrcell_sunspec/commit/610bd99a07eaa46768cacdeda3108e1a86c65bdf))
* eliminate redundant static files in pwrcell/data ([e00ad4d](https://github.com/edalquist/pwrcell_sunspec/commit/e00ad4defa2cd30fe9b8d4bb7ab5a925fc078c03))
* **grouping:** unify compound, concept, and comparison abstractions ([2bf7421](https://github.com/edalquist/pwrcell_sunspec/commit/2bf7421da3cb1eef4ce67a29093536967b81bf58))
* **ha:** exact-match key selection on normalized serial-qualified keys ([b6b69d6](https://github.com/edalquist/pwrcell_sunspec/commit/b6b69d6c762cd12088d423f7a65d1f24e054ba9b))
* **ha:** load controllable allowlists and device labels from config files ([4259737](https://github.com/edalquist/pwrcell_sunspec/commit/425973728e491248d2c4afd421c4458417287926))
* **mapping:** eliminate in-code telemetry mappings and synonyms in favor of YAML ([525f554](https://github.com/edalquist/pwrcell_sunspec/commit/525f554b5a066ed34b35dbb6e39bbbc2dbe5a886))
* replace is_compound/poller/bridge getattr probing with real attributes ([e0657b4](https://github.com/edalquist/pwrcell_sunspec/commit/e0657b45010b9f25f49029b4ddc5cea23d0d69af))
* resolve configuration from system discovery and declarative YAML files ([22df8a7](https://github.com/edalquist/pwrcell_sunspec/commit/22df8a73bfcb284bc564bf49460dd87476154088))
* simplify tier config parsing, name mock tick constant, rename models.py to model_sync.py ([11da481](https://github.com/edalquist/pwrcell_sunspec/commit/11da481bc593439df8f00008404fb201cea631e3))
* **state:** declarative MQTT-to-field tables for telemetry ingestion ([491289f](https://github.com/edalquist/pwrcell_sunspec/commit/491289f33c7723d413a1768421ce004637c96f84))
* **state:** split set_field into metadata, counter-guard and field-merge helpers ([b06e05d](https://github.com/edalquist/pwrcell_sunspec/commit/b06e05dc9674bb53ae6e18ff581bcf4c6de4048c))
* **telemetry:** load MQTT telemetry specs from YAML and derive protobuf enums dynamically ([abd1a78](https://github.com/edalquist/pwrcell_sunspec/commit/abd1a78df4644f8f477773bb17ef4e4cc1f67876))
* **ui:** split create_app routes into Flask blueprints ([33f26c0](https://github.com/edalquist/pwrcell_sunspec/commit/33f26c0c6001e801f086c8f5c3824b9bb8ac2b21))

## [3.8.0] - 2026-11-26

### Added
- **Out-of-Band Restriction Overrides via Home Assistant Add-on Configuration (`config.yaml`, `translations/en.yaml`, `pwrcell/setup_key.py`, `pwrcell/config.py`, `pwrcell/safety.py`, `DOCS.md`)**:
  - Added `blocked_fields` (positive block overrides) and `unblocked_fields` (negative allow overrides) options to the Home Assistant Add-on Configuration schema (`config.yaml`) and `translations/en.yaml`, piped via `setup_key.py` into `/data/pwrcell.yaml` and supported in standalone `config/pwrcell.yaml` via `AppConfig`.
  - Layered overrides cleanly on top of the bundled `config/blocked_fields.yaml` defaults with `unblocked_fields` taking precedence over `blocked_fields`, plus serial-scoped pattern matching (`<SERIAL>:<field_key>`) without leaking plain wildcards into serial prefixes.
  - Updated `/api/safety/blocked_fields` (`get_blocked_mutation_fields()`) and the read-only **🔒 Safety Policy** modal (`pwrcell/ui/static/index.html`, `pwrcell/ui/static/app.js`) to display active override patterns (`override` badges) and any default-protected fields explicitly unblocked by user override.

### Fixed
- **Unify Home Assistant Writability on `config/blocked_fields.yaml` (Issue #35 follow-up — `pwrcell/ha.py`, `config/ha_default_config.yaml`)**:
  - Removed the hidden 10-field `HA_WRITABLE_ALLOWLIST` / `controllable_fields` gate from `is_ha_writable_allowed()` so `config/blocked_fields.yaml` is the single source of truth for write restrictions across the Web Explorer, REST API, `ControlDispatcher`, and Home Assistant MQTT Discovery.
  - Restored Home Assistant interactive `select`/`number` controls (and live `command_topic` subscriptions in `pwrcell/bridge.py`) for unblocked `RW` operational registers such as Enable Inverter (`inverter.EIconfig.Conn`), Enable/Disable PV Link (`pv_link.pvlink_status.Ena`), Enable/Disable String (`battery.lithium_ion_string.SetEna`), `battery.lithium_ion_string.SetCon`, `battery.battery.SetOp`, and `rebus_beacon.REbus_dir.devices.*.Ena`, while ensuring unblocking any field in `config/blocked_fields.yaml` takes effect in Home Assistant as documented.
  - Guarded `is_ha_writable_allowed()` and `generate_discovery_payload()` so non-interactive SunSpec types (`bitfield`, `string`, `ipaddr`, `ipv6addr`, `eui48`, `pad`, and scale factors) always export as read-only `sensor` entities without `command_topic`, while continuing to exclude `SAFETY_SHUTDOWN` from `select` options.
- **Hardened Default Protection List (`config/blocked_fields.yaml`, `config/blocked_fields.example.yaml`)**:
  - Added grid-code compliance and ride-through curve registers (`inverter.SA_defaults.*`, `volt_var`, `volt_watt`, `freq_watt`, `hvrt*`, `lvrt*`, `hfrt*`, `lfrt*`, `ext_settings.AGra`, `output_controls.VarRamp`), device addressing (`*.common.DA`), flash access (`*.flash_reader.*`), rapid shutdown config (`pv_link.pvrss_config.*`, `pv_link.pvlink_status.AMax`), Beacon directory clear/IP settings (`rebus_beacon.REbus_dir.Clr`, `rebus_beacon.ip_settings.*`), and installer/PLM/transfer-switch registers (`inverter.EIconfig.Pwd`, `PLM*`, `GPLM*`, `CTTrig`, `XFR*`) so they are consistently protected everywhere.
- **Unit Tests (`tests/test_safety.py`, `tests/test_bridge.py`, `tests/test_tunnel.py`, `tests/test_ui.py`)**: Added full-device mock `RW` invariant tests verifying Web Explorer and Home Assistant writability match `blocked_fields.yaml` and register types, unblock transition tests for non-legacy protected registers, positive/negative override precedence and serial-scoping tests, `setup_key`/API audit tests, and end-to-end MQTT command execution tests for Enable Inverter, PV Link, and Battery String controls.

## [3.7.0](https://github.com/edalquist/pwrcell_sunspec/compare/v3.6.2...v3.7.0) (2026-11-25)


### Added

* **beacon:** add offline Beacon SD-card image provisioner (v3.5.0) ([380f8ed](https://github.com/edalquist/pwrcell_sunspec/commit/380f8ed4edc3bc0b4bd9a13c66351ab4f4d58a9d))
* **beacon:** add reusable idempotent local-only Beacon hardening script (v3.4.0) ([0c27cb2](https://github.com/edalquist/pwrcell_sunspec/commit/0c27cb2a7ec220434396933fc6a7b61e9d7f4af6))
* collapsible sub-group rollup rows and wildcard HA rules (v3.3.0) ([9ddea7c](https://github.com/edalquist/pwrcell_sunspec/commit/9ddea7c16aa15c31e21b1859f485d54dc645e795))
* **compare:** rework compare telemetry to verify all grouped registers and flag discrepancies ([acd9ef1](https://github.com/edalquist/pwrcell_sunspec/commit/acd9ef1dc2661e1a7cbdcaf65cadca433f028f58))
* **controls:** support custom bounds on mutable fields for proxy and home assistant ([81cc5ed](https://github.com/edalquist/pwrcell_sunspec/commit/81cc5edc678d5a1beecf7d90ca429c78207a7a03))
* generic SunSpec sub-group support (v3.2.0) ([a6218b6](https://github.com/edalquist/pwrcell_sunspec/commit/a6218b626b2e65b97f541e776012dc1a50d6c5df))
* **grouping:** add export for generalized groupings and telemetry mappings ([862d83f](https://github.com/edalquist/pwrcell_sunspec/commit/862d83f6faea017d6c812e6078b9a892301fae13))
* **ha:** purge stale concept entities, enable all selected sensors, add UI reset/clean actions, bump to 3.0.14 ([1660362](https://github.com/edalquist/pwrcell_sunspec/commit/166036237e81e0d31bb665f7f34dac78f15185b7))
* migrate to v2.0 groupings, enforce strict device isolation, and optimize polling ([3bc2409](https://github.com/edalquist/pwrcell_sunspec/commit/3bc2409df780709605a6cfc83078b69b3491fbbf))
* **mqtt:** deduplicate compound entities, add read/write controls, persistence cleanup, and precision formatting ([83fd473](https://github.com/edalquist/pwrcell_sunspec/commit/83fd473be4f852cc0f18eff416f459a5a24e587d))
* **mqtt:** use add-on unique container hostname as default MQTT client ID, bump version to 3.0.5 ([8010053](https://github.com/edalquist/pwrcell_sunspec/commit/801005317e34c240bc5fb8276798f6c9725485e2))
* **optimizer:** merge inverter output exported energy across MQTT, M102 Wh, and M64207 E ([0b56372](https://github.com/edalquist/pwrcell_sunspec/commit/0b5637250169cc870e125c720917e437f54727b0))
* **optimizer:** unified field grouping, minimal model polling solver, and UI explorer enhancements, bump to 3.0.11 ([7f5bfc8](https://github.com/edalquist/pwrcell_sunspec/commit/7f5bfc85df01f7ade1ed8cbc49d288b73b9c63de))
* **recommender:** add recommendation engine and approval endpoints ([fb6672b](https://github.com/edalquist/pwrcell_sunspec/commit/fb6672bacf44c16f812eb138ed00cb349c990e3c))
* strict explicit telemetry grouping, negation handling, and model isolation ([9e80db6](https://github.com/edalquist/pwrcell_sunspec/commit/9e80db663f543a9bfc7fc957b4a44b9ffa3977c6))
* sub-group isolation and rolled-up comparisons and suggestions (v3.2.0) ([063a218](https://github.com/edalquist/pwrcell_sunspec/commit/063a218ad3d768fbc6734fc41cb710306d428ac4))
* **ui,grouping:** add UI options to group, ungroup, and customize field concepts ([43f0a09](https://github.com/edalquist/pwrcell_sunspec/commit/43f0a0977da67953b1a55d39c954e7f42f8fbd5f))
* **ui:** add Export Mappings modal with dual format switcher ([76b4982](https://github.com/edalquist/pwrcell_sunspec/commit/76b4982b54562210bb5d1d87bb8f1ac8cb1d51ca))
* **ui:** add grouping suggestions tab and approval workflow ([9c14fe8](https://github.com/edalquist/pwrcell_sunspec/commit/9c14fe83e213b38854171e29d6ed9301cd658f8d))
* **ui:** add modal and actions to configure field bounds from UI ([8c396e4](https://github.com/edalquist/pwrcell_sunspec/commit/8c396e4e00f364e0ce3e42467b9461fa904d2d2c))
* **ui:** add Modbus and SunSpec register details explorer and bounds restrictions for settable fields, bump to 3.0.10 ([067a18e](https://github.com/edalquist/pwrcell_sunspec/commit/067a18ee46f3c98dbb7a50eceeedde72b302ae8d))
* **ui:** add option to force full device re-scan and clear device cache (v3.1.2) ([2304589](https://github.com/edalquist/pwrcell_sunspec/commit/230458928dca97048e04e1e6802ba4c5cf993e43))
* **ui:** make Web Explorer responsive for mobile and add Playwright desktop/mobile UI tests (v3.6.0) ([3633436](https://github.com/edalquist/pwrcell_sunspec/commit/363343638709bf6e909d41d35f842377099f5751))
* **validation:** add physical plausibility bounds and cumulative energy drop protection, bump to 3.0.7 ([71b9e64](https://github.com/edalquist/pwrcell_sunspec/commit/71b9e64459aca9f20730973522ec30d9e94a1bef))


### Fixed

* **addon:** generate pwrcell.yaml safely via yaml.safe_dump with 0600 permissions ([19ef20c](https://github.com/edalquist/pwrcell_sunspec/commit/19ef20cec8358822d9a4f8ab9f022c1cf43d6185))
* **addon:** set init: false in config.yaml to allow s6-overlay to run as PID 1, bump version to 3.0.2 ([beae950](https://github.com/edalquist/pwrcell_sunspec/commit/beae9506b4a655374e353075bf7fca86f1935ade))
* **beacon:** restore and monitor local MQTT telemetry feed in local-only mode (v3.6.1) ([e453d63](https://github.com/edalquist/pwrcell_sunspec/commit/e453d6356c34fd9b4f3eabc3c1c1efbb2fed3ffe))
* **bridge:** add per-device freshness availability, HA birth republish, and separate poll success tracking ([1e41ca8](https://github.com/edalquist/pwrcell_sunspec/commit/1e41ca823a2b9c57bc8696f2f283024cbf69ad95))
* **bridge:** ignore retained command messages on MQTT command topics ([1478c22](https://github.com/edalquist/pwrcell_sunspec/commit/1478c22b04671927da69308fde6019cebc63db4a))
* **bridge:** import os and only mark _running after start succeeds ([14608bc](https://github.com/edalquist/pwrcell_sunspec/commit/14608bcdff7e69bb799e94f3be7d36cc710fc233))
* **bridge:** return None for invalid/sentinel values in format_state_value and preserve strings ([b73e9f3](https://github.com/edalquist/pwrcell_sunspec/commit/b73e9f3c76f14c350e41342a5e7a75e5aaa6a0c0))
* **bridge:** use single-worker command executor and log listener errors at WARNING ([1977fae](https://github.com/edalquist/pwrcell_sunspec/commit/1977fae35793444ea6eb31700adead248c37d751))
* **catalog:** align JSON model point offsets with XML and prevent repeating subgroup collisions ([42296cf](https://github.com/edalquist/pwrcell_sunspec/commit/42296cf5535fbebdf6aceaa04fa90a2f6d199e17))
* **catalog:** consolidate get_suggested_precision into catalog ([1a6b43e](https://github.com/edalquist/pwrcell_sunspec/commit/1a6b43e2baee2b7d73e8943b6dfaab8ac4f1d5d6))
* **catalog:** deduplicate scale factor point detection into is_scale_factor_point ([29c02b6](https://github.com/edalquist/pwrcell_sunspec/commit/29c02b6b4892f65b8d39a7383c1f064d34f8abd4))
* **catalog:** define named SunSpec model ID constants and resolve control models by name ([ce7fd3c](https://github.com/edalquist/pwrcell_sunspec/commit/ce7fd3c628bac1515c72b8bf7e848eb6ccbbb0f0))
* **ci:** add sanitized test fixtures and fix Release Please config.yaml updater (v3.3.2) ([f2aedee](https://github.com/edalquist/pwrcell_sunspec/commit/f2aedeeb792bc28eaad71df7e1ff2e83896fde4b))
* **client:** classify discovered devices by SunSpec model IDs and skip persisting empty scans ([fc40b69](https://github.com/edalquist/pwrcell_sunspec/commit/fc40b69d1d0306d82e0c3d104cc0d26d705fd2d5))
* **client:** import List in pwrcell.client ([4eacfb6](https://github.com/edalquist/pwrcell_sunspec/commit/4eacfb66a60cd288a332bdffd6fc1897fde0e34f))
* **client:** make mock sim loop interruptible on stop ([f7a4890](https://github.com/edalquist/pwrcell_sunspec/commit/f7a4890821a28e31f84c268919e67ba7ae64054d))
* **client:** revalidate cached device serials against Model 1 and add rescan endpoint ([92d33d2](https://github.com/edalquist/pwrcell_sunspec/commit/92d33d281931c52a663ee834e989af31760d3fb6))
* **cli:** support --log-level both before and after service subcommand, bump version to 3.0.3 ([42d493c](https://github.com/edalquist/pwrcell_sunspec/commit/42d493c9f3960814ef829041056713b40bf08deb))
* **concurrency:** release locks before blocking thread joins, Modbus sync, and MQTT discovery I/O ([8437d73](https://github.com/edalquist/pwrcell_sunspec/commit/8437d73cfe1e6317c89aeb969f316ee1102707f5))
* **concurrency:** synchronize shared state access and replace StateField immutably ([f46f6bc](https://github.com/edalquist/pwrcell_sunspec/commit/f46f6bc5fcb7da1f43dfd8f82dbbda147da84cac))
* **config:** centralize persistent runtime paths under data_dir() ([b17af4f](https://github.com/edalquist/pwrcell_sunspec/commit/b17af4fc7f63556a1b48ffc5cdebc4708b505f56))
* **config:** tolerate null/empty device categories in devices.yaml (v3.5.1) ([f4dadc6](https://github.com/edalquist/pwrcell_sunspec/commit/f4dadc6e82e35a6182d95b2695120c212bc35cff)), closes [#30](https://github.com/edalquist/pwrcell_sunspec/issues/30)
* **config:** type DeviceConfig.read as Optional and fail loudly on malformed AppConfig ([66fd408](https://github.com/edalquist/pwrcell_sunspec/commit/66fd408fbd03fac29a0e1c6172d41db7a1c82e81))
* **controls:** support scaled writable registers and derive HA number bounds from register bounds ([f44cf42](https://github.com/edalquist/pwrcell_sunspec/commit/f44cf42fa813a0d6c232f9ad49c1cadd73127e66))
* **deps:** update alpine docker tag to v3.24 ([#34](https://github.com/edalquist/pwrcell_sunspec/issues/34)) ([7289639](https://github.com/edalquist/pwrcell_sunspec/commit/72896399a1ef6fed6ec1ec4ab6a85ce602cba0b3))
* **deps:** update dependency dataconf to v4 ([d67f222](https://github.com/edalquist/pwrcell_sunspec/commit/d67f222c388c115ef38cdca6d40ba1eecd1a6808))
* **deps:** update dependency dataconf to v4 ([b204d7a](https://github.com/edalquist/pwrcell_sunspec/commit/b204d7a0cd4d8040d4d0fb3c93fd1916e12e4178))
* **deps:** update dependency flask to v3.1.3 [security] ([#28](https://github.com/edalquist/pwrcell_sunspec/issues/28)) ([aa749ef](https://github.com/edalquist/pwrcell_sunspec/commit/aa749efbc3ed4d6471f29b8b404827a2da604182))
* **deps:** update dependency pyyaml to v6.0.4 ([#31](https://github.com/edalquist/pwrcell_sunspec/issues/31)) ([80bc335](https://github.com/edalquist/pwrcell_sunspec/commit/80bc335b5ee7c0fddbc904e4551734da0b574998))
* **deps:** update ghcr.io/home-assistant/base-python docker tag to v3.15 ([#24](https://github.com/edalquist/pwrcell_sunspec/issues/24)) ([cc4ad84](https://github.com/edalquist/pwrcell_sunspec/commit/cc4ad847af86c9899d1d57972bc99e2faf5934c7))
* **deps:** update python non-major dependencies ([#22](https://github.com/edalquist/pwrcell_sunspec/issues/22)) ([503091d](https://github.com/edalquist/pwrcell_sunspec/commit/503091dac192ffceaf8688e8086c390a94ce3de0))
* **ha:** address discovery audit issues and gateway node, bump to 3.0.13 ([a575a22](https://github.com/edalquist/pwrcell_sunspec/commit/a575a22ae97c946a35c5bbc70cd65f83605fc4b4))
* **ha:** export protected and non-writable fields as read-only sensors (v3.6.2) ([242549f](https://github.com/edalquist/pwrcell_sunspec/commit/242549fff4cf2b08834ccb0a641091890a7da776))
* **ha:** handle null or empty selected_fields in ha_config.yaml gracefully ([18d7606](https://github.com/edalquist/pwrcell_sunspec/commit/18d76064294e728e6ee3c8dce66938a14e45e2c6))
* **ha:** preserve full sensor precision and scale-factor display precision (v3.2.2) ([7b99e49](https://github.com/edalquist/pwrcell_sunspec/commit/7b99e49475589a32a1f471d4fe7d31a875654187))
* **ha:** prevent duplicate entities on group selection and fix inverter_state enum mapping (v3.1.6) ([bd11a4c](https://github.com/edalquist/pwrcell_sunspec/commit/bd11a4c6a2496e561a5e5ec1e02499cfcb0478d2))
* **ha:** require yaml, write HA config atomically, and use full serial in object_id ([93507d8](https://github.com/edalquist/pwrcell_sunspec/commit/93507d88ed065df0d6991522a255fc6bd1606eac))
* **ha:** resolve inverter_state enum mapping, deduplicate system_mode options, and retain compound states (v3.1.7) ([16bbc99](https://github.com/edalquist/pwrcell_sunspec/commit/16bbc9935dab2d9c7355ae9b0ede4c9f91c87e7d))
* **ha:** restrict writable discovery exposure to explicit allow-list and exclude SAFETY_SHUTDOWN ([9ace5ff](https://github.com/edalquist/pwrcell_sunspec/commit/9ace5ff9f3e3f70b8dad428435743b52fa55b00b))
* **ha:** seed devices from ha_default_config when ha_config is missing or empty ([bd94f2c](https://github.com/edalquist/pwrcell_sunspec/commit/bd94f2c9caf169753293551e8ef172011d5b1571))
* **lifecycle:** prevent worker resurrection after close, stop bridge on client stop, and handle SIGTERM ([eff3e27](https://github.com/edalquist/pwrcell_sunspec/commit/eff3e2702a3b0396ee5a8bc9f677a2ed54599123))
* **mapping:** query MappingRegistry dynamically instead of import-time caches ([c724fbf](https://github.com/edalquist/pwrcell_sunspec/commit/c724fbff7043ca8ba1de4ff3ed55e169ea99d3ae))
* **modbus:** log duplicate serial at WARNING and assign synthetic serials to blank-SN devices ([5661a95](https://github.com/edalquist/pwrcell_sunspec/commit/5661a95ba1abfbd292480352d12fea62d7f3b8d2))
* **modbus:** retry only transport errors, lower default socket timeout, and bound consecutive scan misses ([4d72736](https://github.com/edalquist/pwrcell_sunspec/commit/4d72736f7fbea3144472751571bed8383505968c))
* **modbus:** skip duplicate serials instead of aborting scan ([7f7259b](https://github.com/edalquist/pwrcell_sunspec/commit/7f7259bc970cd120f9789709edb8674074ef793d))
* **modbus:** treat socket EOF (b'') during drain as disconnect and reconnect immediately ([835d476](https://github.com/edalquist/pwrcell_sunspec/commit/835d476310af4e9b1e1825a7e05d83a97699e95b))
* **modbus:** verify write read-back value and publish clamped device state ([5d0fa5c](https://github.com/edalquist/pwrcell_sunspec/commit/5d0fa5cd65053a7e9423eddcf42c5a03cfd8c06e))
* **models:** pin SSH host keys (TOFU), stage SCP downloads atomically, and warn on sync failure ([377571f](https://github.com/edalquist/pwrcell_sunspec/commit/377571f2e2f1be819d4c7598c856edf59a246ecd))
* **modes:** separate SunSpec SysMd and MQTT proto mode tables and remove broken fallbacks ([6ad8773](https://github.com/edalquist/pwrcell_sunspec/commit/6ad877325b920f73ab63ed17c7684c48e1fd1f6e))
* **mqtt:** do not abort client startup when initial MQTT connect fails ([f08a1f2](https://github.com/edalquist/pwrcell_sunspec/commit/f08a1f254a6c5816a6dc507c87c2eccc2b8c2f8b))
* **mqtt:** format large numbers and energy values without scientific notation ([4cfd35f](https://github.com/edalquist/pwrcell_sunspec/commit/4cfd35f0b8ce593b92355f49e8f0790cf96ea2aa))
* **mqtt:** subscribe narrowly to energy_recordset_live and reconnect only when tunnel port changes ([d978122](https://github.com/edalquist/pwrcell_sunspec/commit/d9781220503a8d771661fe11f7ef70d1402b3d38))
* **optimizer,correlator:** resolve voltage, state, polarity, and energy grouping discrepancies ([f5b496f](https://github.com/edalquist/pwrcell_sunspec/commit/f5b496f22ee7bc199c46e96742976fd116726497))
* **optimizer:** fix swapped TotWhImp and TotWhExp synonyms in CANONICAL_SYNONYMS ([e0e0fbb](https://github.com/edalquist/pwrcell_sunspec/commit/e0e0fbb4cf304b45c22580b2d6d01b0ebf8d6139))
* **optimizer:** normalize %WHRtg unit to % in clean_unit ([b3b39eb](https://github.com/edalquist/pwrcell_sunspec/commit/b3b39eb314a5cefb1c93b5b57ed520c872dc8c0f))
* **poller:** derive DEFAULT_*_MODELS from DEFAULT_*_PATHS ([80dd9a1](https://github.com/edalquist/pwrcell_sunspec/commit/80dd9a1dee04b60f985c1543fd5ab8e730ac148b))
* **poller:** make startup stagger stoppable and simplify tier schedule loop ([40e5ad3](https://github.com/edalquist/pwrcell_sunspec/commit/40e5ad30e9ee1e23c9af0a5969ba8317532612a4))
* **poller:** narrow exception handling and log at debug in safe_point_cvalue ([d9cf5e3](https://github.com/edalquist/pwrcell_sunspec/commit/d9cf5e3cd4d45cf7199b958968531af2942e1c39))
* **poller:** poll all instances of repeating SunSpec models with indexed subgroup keys ([19520cc](https://github.com/edalquist/pwrcell_sunspec/commit/19520cc625ea100a58684e0f4290ce45a9c02dde))
* **poller:** unify subgroup-to-model-ID resolution with exact segment matching ([a2292b7](https://github.com/edalquist/pwrcell_sunspec/commit/a2292b7eb8682ae7265e1f345a2fca037695105d))
* **poller:** validate polling tier in trigger_sync and return 400 on invalid tier ([feb23c7](https://github.com/edalquist/pwrcell_sunspec/commit/feb23c7e407897b1e6c3f9e629bd2ee3c528106f))
* resolve grouping, mqtt discovery, and combined sensor jitter issues (v3.1.5) ([54fa90c](https://github.com/edalquist/pwrcell_sunspec/commit/54fa90c428d76973a15b0cf446762c0728718df2))
* **setup_key:** create SSH private key file with mode 0600 before writing ([f712e42](https://github.com/edalquist/pwrcell_sunspec/commit/f712e42a041857a075ec80db7adce4e1c3e3df5b))
* **setup_key:** handle PermissionError when probing default SSH key paths (v3.3.3) ([39c26e2](https://github.com/edalquist/pwrcell_sunspec/commit/39c26e2147a3be099eb284c3a5176e5688e2aff2))
* **ssh:** add SSH key normalizer to handle single-line/escaped keys, support passphrase & password, bump version to 3.0.4 ([2ce96ca](https://github.com/edalquist/pwrcell_sunspec/commit/2ce96ca5b5ca384a97aca445ca58d2617046b833))
* **state:** drive plausibility bounds from units/device_class, not name substrings ([758c388](https://github.com/edalquist/pwrcell_sunspec/commit/758c388228d641324487fcfbf32d89cc7039d92a))
* **state:** exempt pv_link session energy counters from drop suppression, bump to 3.0.9 ([7e20d4a](https://github.com/edalquist/pwrcell_sunspec/commit/7e20d4a83ab85722ce51c5b61927b6d35c217f25))
* **state:** guard SUNSPEC_SENTINELS membership checks against unhashable values ([fe4a928](https://github.com/edalquist/pwrcell_sunspec/commit/fe4a9282e1c16184dad2e337fe7b49d15483876a))
* **state:** normalize NaN/inf raw_value to None and remove unreachable NaN branch ([7ac9576](https://github.com/edalquist/pwrcell_sunspec/commit/7ac95767f35cc4d9d9834306286e4380f6021bc5))
* **state:** publish zero voltage, inverter state, and battery power limits from MQTT ([14cc721](https://github.com/edalquist/pwrcell_sunspec/commit/14cc721552d003c8e7ffdc7a618c74e8261e1e6c))
* **state:** remove home-grown scale factor cases in update_from_modbus_points ([939f48b](https://github.com/edalquist/pwrcell_sunspec/commit/939f48bf8e10a5234e6d20b4577130943acd748e))
* **state:** replace permanent monotonic counter latch with N-consecutive confirmation ([4cbd453](https://github.com/edalquist/pwrcell_sunspec/commit/4cbd4538f667c128f2cce92e75614564dd3f9cdb))
* **state:** suppress out-of-bounds warning log-spam and handle vendor pseudo-sentinels (v3.2.1, fixes [#15](https://github.com/edalquist/pwrcell_sunspec/issues/15)) ([d4bd31a](https://github.com/edalquist/pwrcell_sunspec/commit/d4bd31ae1031c815de07ab6b0ab1964c9cb06057))
* **sunspec:** evaluate sentinels by register type at raw level only ([45653fb](https://github.com/edalquist/pwrcell_sunspec/commit/45653fb23728e7b31a210b5fd4b605aeadc2554b))
* **sunspec:** resolve math range error and scale factor sentinel corruption, bump to 3.0.6 ([885a6cd](https://github.com/edalquist/pwrcell_sunspec/commit/885a6cda8a9c28cb3018b21997b52e1758264c01))
* **ui,recommender:** exclude scale factor registers from merging UI and suggestions ([d9febe1](https://github.com/edalquist/pwrcell_sunspec/commit/d9febe1f1b79929e1d137d42a5ae0e8fedca11ce))
* **ui:** dynamically display package version instead of hardcoded v3.0 (v3.2.0) ([7d11a80](https://github.com/edalquist/pwrcell_sunspec/commit/7d11a801f0e77fb9bda9be83b1ea7930d5094c67))
* **ui:** remove stray syntax tokens in app.js breaking client execution ([4dad7c7](https://github.com/edalquist/pwrcell_sunspec/commit/4dad7c7c41f89b46dd61d352e615fc0b5ed24280))
* **ui:** use selectDevice instead of fetchDeviceFields after grouping change ([d6cb407](https://github.com/edalquist/pwrcell_sunspec/commit/d6cb4070e7d32592578f51cc01e3911bc5886b36))
* **ui:** use SUNSPEC_SYS_MD_NAMES instead of inverted OPERATING_MODES dict ([10ffaf8](https://github.com/edalquist/pwrcell_sunspec/commit/10ffaf8e88ffff1ff643f1aeb67479f2cb07c683))
* **upgrade:** reconcile persisted groupings, separate AC/DC energy, and restore PV Link primary defaults (v3.2.0) ([0bc3d9f](https://github.com/edalquist/pwrcell_sunspec/commit/0bc3d9ffdff2e5023288462d6255dd2d5078f478))
* **validation:** calibrate plausibility bounds for commercial ratings, bump to 3.0.8 ([bf0ed9d](https://github.com/edalquist/pwrcell_sunspec/commit/bf0ed9dfd49216ce0d12d22ad6455ea22b342f07))
* **version:** derive HA ORIGIN_INFO sw_version from __version__ and align config.yaml ([44f8b25](https://github.com/edalquist/pwrcell_sunspec/commit/44f8b25cfef0a7291fd040baf97f2855bdb41c89))


### Changed

* **catalog,optimizer:** externalize fallback point abbreviations and optimizer preferences to YAML ([5c5f776](https://github.com/edalquist/pwrcell_sunspec/commit/5c5f776b4b90e270dc11ca607a9242d92f059aa9))
* **controls:** derive system operating modes and symbols dynamically from SunSpec metamodels ([5440dff](https://github.com/edalquist/pwrcell_sunspec/commit/5440dfff2dfb9b3048a020a147256641a2c33227))
* **devices:** externalize device types, model classification rules, and tier paths to YAML configs ([610bd99](https://github.com/edalquist/pwrcell_sunspec/commit/610bd99a07eaa46768cacdeda3108e1a86c65bdf))
* eliminate redundant static files in pwrcell/data ([e00ad4d](https://github.com/edalquist/pwrcell_sunspec/commit/e00ad4defa2cd30fe9b8d4bb7ab5a925fc078c03))
* **grouping:** unify compound, concept, and comparison abstractions ([2bf7421](https://github.com/edalquist/pwrcell_sunspec/commit/2bf7421da3cb1eef4ce67a29093536967b81bf58))
* **ha:** exact-match key selection on normalized serial-qualified keys ([b6b69d6](https://github.com/edalquist/pwrcell_sunspec/commit/b6b69d6c762cd12088d423f7a65d1f24e054ba9b))
* **ha:** load controllable allowlists and device labels from config files ([4259737](https://github.com/edalquist/pwrcell_sunspec/commit/425973728e491248d2c4afd421c4458417287926))
* **mapping:** eliminate in-code telemetry mappings and synonyms in favor of YAML ([525f554](https://github.com/edalquist/pwrcell_sunspec/commit/525f554b5a066ed34b35dbb6e39bbbc2dbe5a886))
* replace is_compound/poller/bridge getattr probing with real attributes ([e0657b4](https://github.com/edalquist/pwrcell_sunspec/commit/e0657b45010b9f25f49029b4ddc5cea23d0d69af))
* resolve configuration from system discovery and declarative YAML files ([22df8a7](https://github.com/edalquist/pwrcell_sunspec/commit/22df8a73bfcb284bc564bf49460dd87476154088))
* simplify tier config parsing, name mock tick constant, rename models.py to model_sync.py ([11da481](https://github.com/edalquist/pwrcell_sunspec/commit/11da481bc593439df8f00008404fb201cea631e3))
* **state:** declarative MQTT-to-field tables for telemetry ingestion ([491289f](https://github.com/edalquist/pwrcell_sunspec/commit/491289f33c7723d413a1768421ce004637c96f84))
* **state:** split set_field into metadata, counter-guard and field-merge helpers ([b06e05d](https://github.com/edalquist/pwrcell_sunspec/commit/b06e05dc9674bb53ae6e18ff581bcf4c6de4048c))
* **telemetry:** load MQTT telemetry specs from YAML and derive protobuf enums dynamically ([abd1a78](https://github.com/edalquist/pwrcell_sunspec/commit/abd1a78df4644f8f477773bb17ef4e4cc1f67876))
* **ui:** split create_app routes into Flask blueprints ([33f26c0](https://github.com/edalquist/pwrcell_sunspec/commit/33f26c0c6001e801f086c8f5c3824b9bb8ac2b21))

## [3.6.2] - 2026-11-24

### Fixed
- **Protected & Non-Writable Fields Exported as Read-Only `sensor` Entities in Home Assistant (Issue #35 — `pwrcell/ha.py`, `pwrcell/state.py`, `pwrcell/concept.py`, `pwrcell/optimizer.py`)**:
  - Added `get_effective_ha_platform()` in `pwrcell/ha.py` so `generate_discovery_payload()` only emits interactive `select`/`number`/`switch` platforms when `is_ha_writable_allowed()` is `True`, downgrading mutation-blocked (`config/blocked_fields.yaml`) and non-allowlisted `RW` registers from catalog `ha_hint` platforms to read-only `sensor` entities without `command_topic`, `min`/`max`/`step`/`mode`, or `options` (while preserving `device_class: "enum"` and `options` on true read-only enum sensors).
  - Updated `get_effective_ha_category()` so read-only/downgraded sensors default to `entity_category: "diagnostic"` instead of `"config"` (which Home Assistant rejects on `sensor` entities), and safely coerce any `"config"` user override on a read-only sensor to `"diagnostic"` while still honoring `"primary"`/`"diagnostic"` overrides.
  - Added automatic cleanup of stale `select`/`number`/`switch` MQTT discovery topics in `legacy_config_topics` when a field exports as `sensor`, removing previously published interactive controls from Home Assistant on upgrade or after blocking a register.
  - Aligned `StateField.to_dict()`, `StateStore.get_compound_view()`, `ConceptView.to_dict()`, and `group_device_fields()` in `pwrcell/optimizer.py` with `get_effective_ha_platform()` and `get_effective_ha_category()` so the REST API and Web Explorer accurately display protected/non-HA-writable fields as `sensor` and omit writable `ha_options`.
- **Unit Tests (`tests/test_safety.py`, `tests/test_bridge.py`, `tests/test_ha_discovery_audit.py`)**: Added regression tests covering protected `RW` enum/numeric discovery, dynamic block/unblock transitions in `blocked_fields.yaml`, stale `select`/`number`/`switch` topic purging, `config` category coercion, and Web Explorer / API metadata alignment.

## [3.6.1] - 2026-11-24

### Fixed
- **Local Beacon MQTT Telemetry Feed Stall (`util/beacon_local_only.sh`, `tests/test_beacon_local_only.py`)**:
  - Replaced cloud-dependent `mqtt_active` monitoring with an active local MQTT liveness watchdog (`local_mqtt_live` via `/opt/pika/bin/check_local_mqtt_live.sh`) that verifies `sd_pusher` is actively emitting on `127.0.0.1:1883` (`local/energy_recordset_live`) and restarts `S58statuspusher` if Generac's `sd_pusher.pyc` hits its upstream `autopush_lock` self-deadlock on `SDDatabaseException("database is locked")`.
  - Added offline `sd_poller.db` cloud upload queue pruning (`/etc/cron.hourly/prune_sd_poller_cloud_queue`, deleting `web_packages WHERE sent_to_server=0`, plus an initial stopped-service `DELETE` + `VACUUM` when `sd_poller.db` is `>= 50 MiB`; opt out via `--keep-poller-db`) to eliminate 10–20s `PRAGMA integrity_check` SQLite lockouts that crashed `sd_poller` and deadlocked `sd_pusher`.
  - Added post-apply `S58statuspusher` recovery/verification whenever Mosquitto is restarted or `local/energy_recordset_live` is silent, and wrapped `mosquitto` restarts in `monit unmonitor/monitor mosquitto` so `monit` does not race and double-restart Mosquitto and `system_controller`.
  - Added `--status` checks for `local_mqtt_live`, `local/energy_recordset_live` (`LIVE` vs `SILENT`), and `sd_poller.db` size / unsent `web_packages` / hourly cron prune status, and ordered `--revert` to remove managed scripts only after `monit reload`.

## [3.6.0] - 2026-11-23

### Added
- **Responsive Mobile & Tablet Web Explorer UI (`pwrcell/ui/static/index.html`, `pwrcell/ui/static/style.css`, `pwrcell/ui/static/app.js`, `docs/management_ui.md`)**:
  - Added full responsive layouts for tablet (`<= 1024px`) and mobile / Home Assistant Companion App Ingress WebViews (`<= 768px` and compact `360px`–`430px` viewports) with `viewport-fit=cover` and `env(safe-area-inset-bottom)` support.
  - Added an off-canvas slide-over device drawer (`#deviceSidebar` + `#sidebarBackdrop`) with automatic close on device selection, Escape key dismissal, and automatic cleanup on resize back to desktop.
  - Added compact mobile header (**☰ Devices**, live connection dot, and collapsible **⚙️ Tools** panel), 2-column quick telemetry chip grid with full-width **Mode** selector, and full-width segmented view switcher.
  - Added collapsible toolbar display **Options**, a mobile **Sort** dropdown synced with `state.sortCriteria` and `#sortBar`, horizontally scrollable filter pills, CSS Grid mobile field cards (with viewport-aware `⋮` action menus), and stacked child-source / sub-group rollup cards.
  - Added a sticky compact bottom footer bar with an upward-expanding **More ▴** menu for secondary Home Assistant actions, plus responsive modal dialogs (`#compareModal`, `#modbusDetailsModal`, `#writeModal`, `#groupingModal`, `#boundsModal`, `#blockedSafetyModal`, `#rescanModal`, `#previewModal`, `#exportMappingsModal`, `#exportHADefaultsModal`).
- **Automated Playwright Desktop, Tablet & Mobile Browser UI Test Suite (`tests/test_ui_browser.py`, `tests/test_ui.py`, `requirements-dev.txt`, `.github/workflows/ci.yml`, `renovate.json`)**:
  - Added `tests/test_ui_browser.py` verifying zero horizontal overflow, console/page errors, drawer/menu interactions, search/filtering/sorting, row/rollup expansion, HA config persistence, SSE live updates, modal viewport fit, and dynamic desktop-mobile resize across `1440×900`, `1280×800`, `768×1024`, `390×844`, and `360×680`.
  - Added `requirements-dev.txt` (kept separate from runtime `requirements.txt` for lean add-on containers), Renovate dev-dependency rules (`chore(deps)`), and a dedicated `ui-tests` job in `.github/workflows/ci.yml`.

## [3.5.1] - 2026-11-23

### Fixed
- **Null/Empty Device Categories in `devices.yaml` (Issue #30 — `pwrcell/config.py`, `tests/test_client_lifecycle.py`)**: Updated `DeviceConfig.read()` to parse YAML with `yaml.safe_load()` and normalize empty/null category values (such as bare keys like `pv_link:` written by `dataconf` v3 prior to v3.3.4 or hand-edited files) to `{}` before delegating to `dataconf.dict()`, preventing `MalformedConfigException: expected dict at .<category> but received None` on startup under `dataconf` v4 while continuing to fail loudly on genuinely malformed YAML or invalid field types. Updated `DeviceConfig.write()` to write atomically via `yaml.safe_dump()` so empty categories always serialize as explicit `{}` mappings, and hardened `DeviceConfig.__post_init__()` and `DeviceConfig.get_device_map()` against `None` category values.

## [3.5.0] - 2026-11-23

### Added
- **Offline Beacon SD-Card Image Provisioner (`util/beacon_provision_image.sh`, `util/Dockerfile.beacon-provision`)**: Added an idempotent POSIX `/bin/sh` tool (with automatic privileged Alpine Linux Docker execution on macOS or native execution on Linux) to provision an offline Beacon `.img` file (or extracted overlay/rootfs directories via `--rw-root`/`--ro-root`) with `--status`, `--dry-run`, `--apply`, and `--revert` modes. Validates and appends OpenSSH public keys to `rw/user/root/.ssh/authorized_keys` (`0700`/`0600`, rejecting private keys), enables root pubkey SSH in `rw/user/etc/ssh/sshd_config`, ensures executable `S50sshd`, and inserts `-A INPUT -i <iface> -p tcp --dport <port> -j ACCEPT` rules into `etc/iptables/rules.v4` and `rules.v6` before catch-all `DROP` rules while backing up originals for clean revert.
- **Unit Tests & Documentation (`tests/test_beacon_provision_image.py`, `README.md`, `DOCS.md`)**: Added 10 unit tests covering read-only audit/dry-run, overlay provisioning & idempotency, existing/blocking firewall rules, custom port/interfaces/`--no-ipv6`, non-executable `S50sshd` repair, clean `--revert`, and key/argument validation, plus usage docs in `README.md` and `DOCS.md`.

## [3.4.0] - 2026-11-23

### Added
- **Reusable Local-Only Beacon Hardening Script (`util/beacon_local_only.sh`)**: Added an idempotent, BusyBox-compatible POSIX `/bin/sh` utility (supporting both local execution and SSH `stdin` streaming) to harden internet-blocked Generac REbus Beacons with `--status`, `--dry-run`, `--apply`, and `--revert` modes. Disables cloud-only `monit` watchdogs (`mqtt_reboot`, `mqtt_active`, `ipv6_monitor`, `internet`, `inet_good`, `autossh_triggers`, `sshidle_monitor`, `update_manager`), disables Mosquitto AWS IoT bridges and clears bloated `mosquitto.db` persistence while keeping local `127.0.0.1:1883` MQTT and Modbus TCP intact, installs `/etc/logrotate.d/lcm_binary_log` (`copytruncate`, `size 10M`, `rotate 5`) with safe in-place `O_APPEND` truncation of oversized `/var/log/lcm_core/binary_log` (`>= 100 MiB`, opt-out via `--keep-binary-log`), and supports configuring local LAN NTP servers (`--ntp-server`, fixing the stock `NPSERVERS` typo) or disabling `ntpdate` retries (`--disable-ntp`), with pre-reload `monit -t` validation, rollback on failure, and factory backup restoration.
- **Unit Tests & Documentation (`tests/test_beacon_local_only.py`, `README.md`, `DOCS.md`)**: Added unit test coverage for `util/beacon_local_only.sh` (audit, dry-run, idempotent apply, `binary_log` rotation/in-place truncation, NTP toggle, keep flags, monit/mosquitto rollback, revert, stdin execution, and argument/target guards) along with usage guides in `README.md` and `DOCS.md`.

## [3.3.4](https://github.com/edalquist/pwrcell_sunspec/compare/v3.3.3...v3.3.4) (2026-11-20)


### Fixed

* **deps:** update dependency dataconf to v4 ([d67f222](https://github.com/edalquist/pwrcell_sunspec/commit/d67f222c388c115ef38cdca6d40ba1eecd1a6808))
* **deps:** update dependency dataconf to v4 ([b204d7a](https://github.com/edalquist/pwrcell_sunspec/commit/b204d7a0cd4d8040d4d0fb3c93fd1916e12e4178))
* **deps:** update dependency flask to v3.1.3 [security] ([#28](https://github.com/edalquist/pwrcell_sunspec/issues/28)) ([aa749ef](https://github.com/edalquist/pwrcell_sunspec/commit/aa749efbc3ed4d6471f29b8b404827a2da604182))
* **deps:** update ghcr.io/home-assistant/base-python docker tag to v3.15 ([#24](https://github.com/edalquist/pwrcell_sunspec/issues/24)) ([cc4ad84](https://github.com/edalquist/pwrcell_sunspec/commit/cc4ad847af86c9899d1d57972bc99e2faf5934c7))
* **deps:** update python non-major dependencies ([#22](https://github.com/edalquist/pwrcell_sunspec/issues/22)) ([503091d](https://github.com/edalquist/pwrcell_sunspec/commit/503091dac192ffceaf8688e8086c390a94ce3de0))

## [3.3.3] - 2026-11-19

### Fixed
- **Non-Root `PermissionError` in `generate_config_from_options()` (`pwrcell/setup_key.py`, `tests/test_tunnel.py`)**: Safely handle `OSError` / `PermissionError` when probing default SSH key paths (such as `/root/.ssh/id_rsa_pwrcell` on Linux under Python 3.13) and pass an isolated temp `target_key_path` in `test_generate_config_from_options_handles_special_chars_and_sets_0600`.

## [3.3.2] - 2026-11-19

### Fixed
- **Sanitized CI & Mock-Mode Test Fixtures (`tests/fixtures/model_dump/`, `pwrcell/fixtures.py`, `.gitignore`)**: Added sanitized SunSpec device dump fixtures (with synthetic serial numbers, fake MAC/UUIDs, and documentation IPs) so GitHub Actions CI unit tests and Home Assistant `mock_mode` work out of the box without committing real hardware identifiers.
- **Release Please `config.yaml` Formatting & Version Check (`release-please-config.json`, `config.yaml`, `.github/workflows/ci.yml`)**: Switched `config.yaml` from Release Please's `yaml` updater (which stripped quotes and blank lines) to the `generic` updater with `# x-release-please-version`, and relaxed the CI version check to accept quoted or unquoted YAML version values.

## [3.3.1] - 2026-11-19

### Added
- **GitHub Actions CI (`.github/workflows/ci.yml`)**: Runs the `unittest` suite on Python 3.13 and 3.14, verifies version/changelog synchronization across `config.yaml`, `pwrcell/__init__.py`, `.release-please-manifest.json`, and `CHANGELOG.md`, and performs a Docker build smoke test on PRs and pushes to `main`.
- **Automated Dependency Updates (`renovate.json`)**: Configured Renovate to open weekly grouped PRs for Python, Dockerfile, and GitHub Actions updates, keeping `protobuf` on major version 7 to match the generated protobuf code, tagging runtime dependency updates as `fix(deps)` and CI updates as `chore(ci)`.
- **Automated Releases via Release Please (`release-please-config.json`, `.release-please-manifest.json`, `.github/workflows/release-please.yml`)**: Automatically generates Release PRs, updates `CHANGELOG.md`, keeps `config.yaml` and `pwrcell/__init__.py` versions in sync, and publishes `vX.Y.Z` tags and GitHub Releases from Conventional Commits.

### Changed
- **Cleaned Up `requirements.txt`**: Removed 19 unused/transitive dependency pins (`absl-py`, `bcrypt`, `cffi`, `cryptography`, `dataclasses-json`, `isodate`, `marshmallow`, `mypy-extensions`, `packaging`, `pycparser`, `pyhocon`, `PyNaCl`, `pyparsing`, `pyserial`, `python-dateutil`, `six`, `typing-inspect`, `typing_extensions`, `Werkzeug`), retaining only the 9 direct runtime dependencies pinned with exact versions (`dataconf`, `Flask`, `paho-mqtt`, `paramiko`, `protobuf`, `pysunspec2`, `PyYAML`, `scp`, `sshtunnel`).

## [3.3.0] - 2026-11-18

### Added
- **SSH Tunnel Forced Recovery & Reconnect Listeners (`pwrcell/tunnel.py`)**:
  - Added `PwrCellTunnel.force_reconnect()` with a 15s monotonic cooldown (`_reconnect_count` tracking) to tear down and rebuild wedged SSH tunnel forwards even when `SSHTunnelForwarder.is_active` still reports True.
  - Added `register_reconnect_callback()` / `unregister_reconnect_callback()` and `get_status()` so downstream transports (`MqttClient`, `SerializedModbusClient`) are notified immediately after every tunnel rebuild.
- **Internal Beacon MQTT Connectivity & Staleness Watchdog (`pwrcell/mqtt.py`)**:
  - Added `is_connected`, `last_message_time`, `is_healthy()`, `get_status()`, and `check_health_and_reconnect()` to detect port drift, prolonged broker disconnects (escalating to `force_tunnel=True` on repeated failure), and silent zombie MQTT streams when no telemetry arrives within `mqtt_stale_timeout` (120s).
  - Registered an automatic tunnel reconnect listener in `MqttClient.start()` (`_on_tunnel_reconnected`) to repoint and reconnect the internal MQTT subscriber whenever the SSH tunnel rebuilds.
- **Automatic SunSpec Register-Map Rescan & Modbus Connection Recovery (`pwrcell/modbus.py`, `pwrcell/poller.py`)**:
  - Added `parse_modbus_exception_code()`, `is_address_exception()`, and `is_device_unavailable_exception()` plus `SerializedModbusClient.invalidate_device()`, `rescan_device()`, and `reset_connection()`.
  - Updated `TieredModbusPoller` (`_maybe_rescan_device`) to automatically invalidate, rescan, and retry once on `Modbus exception 2` (Illegal Data Address) or missing previously-supported models (gated by `rescan_cooldown=60s`), verifying Model 1 serial numbers to catch slave ID shifts via full `client.rescan_devices()`.
- **Per-Device & Global Offline Tracking (`pwrcell/state.py`, `pwrcell/poller.py`)**:
  - Added `UnifiedDevice.last_error`, `UnifiedDevice.consecutive_errors`, and `StateStore.set_device_online()` so devices transition to `online=False` after `offline_threshold` (3) consecutive failed poll cycles, mark `modbus_connected=False`, trigger `reset_connection(force_tunnel=True)`, and execute a post-offline recovery rescan when connectivity returns.
  - Invoked `client.mqtt.check_health_and_reconnect()` from `TieredModbusPoller._worker_loop()` on live runs.
- **Web Explorer Live Connectivity Diagnostics (`pwrcell/ui/routes/devices.py`, `pwrcell/ui/static/`)**:
  - Exposed a `"connectivity"` summary (`tunnel_active`, `modbus_connected`, `mqtt_connected`, `mqtt_healthy`, `mqtt_last_message_age`, `ha_mqtt_connected`, `offline_devices`) on `GET /api/overview`, updated the header status indicator (`#liveIndicator` / `#connStatusText`) for degraded/disconnected states, and added offline badges to sidebar device cards.
- Added unit tests covering tunnel force-reconnect, MQTT health watchdog, Modbus exception classification/rescan, poller offline/recovery flows, Home Assistant bridge availability/async reconnect, and Web Explorer connectivity endpoints in `tests/test_tunnel.py`, `tests/test_modbus.py`, `tests/test_poller.py`, `tests/test_bridge.py`, and `tests/test_ui.py`.

### Fixed
- **Home Assistant MQTT Availability & Broker Reconnect Resilience (`pwrcell/bridge.py`)**:
  - Fixed `HomeAssistantBridge.start()` to fall back to `connect_async()` when the initial synchronous `connect()` raises, and added a 60s disconnected reconnect watchdog in `check_availability()` plus `get_status()`.
  - Updated `_is_device_available()` so non-mock `rebus_beacon` gateways reflect simultaneous Modbus and internal MQTT loss, and fixed `publish_discovery()` to publish computed `"online"` / `"offline"` status instead of hardcoded `"online"`.
- Synced `SerializedModbusClient._get_shared_client()` port with the active tunnel even when `_shared_client` is `None` and flagged `_socket_reset_needed` safely on tunnel rebuilds (`pwrcell/modbus.py`).

## [3.2.2] - 2026-11-15

### Fixed
- **Preserve Full Sensor Precision & Scale-Factor-Aware Display Precision in Home Assistant**:
  - Updated `get_suggested_precision()` and `ModelCatalog.derive_ha_metadata()` (`pwrcell/catalog.py`) with `infer_scale_factor_precision()` to derive `suggested_display_precision` from live SunSpec scale factor values (`sf_value`), static scale-factor register names (`CellV_SF`, `sf_1000`, `sf_100`, `A_SF`, `I_sf`, etc.), and cell-voltage point names (excluding integer cell/module index counters like `ModCellVMinCell`). Battery module cell voltages (`ModCellVMin`/`ModCellVMax`/`ModCellVAvg` in Model `804`, `MaxCellV`/`MinCellV` in Model `64252`) now advertise 3 decimal places, `PackV` and 2-decimal current points advertise 2 decimal places.
  - Propagated scale-factor precision across `UnifiedDevice.get_scale_factor_value()`, `StateField.to_dict()`, `StateStore._build_field()`, `StateStore.ensure_field_definition()`, `StateStore.get_compound_view()` (`pwrcell/state.py`), `group_device_fields()` (`pwrcell/optimizer.py`), and `generate_discovery_payload()` (`pwrcell/ha.py`).
  - Stopped rounding/truncating MQTT state payloads in `HomeAssistantBridge` (`pwrcell/bridge.py`) to `suggested_display_precision`, expanded float artifact cleanup in `format_state_value()` to 6 decimal places without scientific notation, and added automatic discovery payload cache refresh (`_get_expected_sensor_precision`) when a scale factor arrives after initial cold-start discovery.

## [3.2.1] - 2026-11-15

### Fixed
- **Suppress Out-of-Bounds Warning Log-Spam & Handle Vendor Pseudo-Sentinels (Issue #15)**:
  - Added `VENDOR_PSEUDO_SENTINELS_BY_TYPE` and `is_vendor_pseudo_sentinel()` (`pwrcell/catalog.py`) to identify non-standard firmware near-boundary sentinels (such as `0xFFFE` / `65534` emitted by some inverter firmware on unimplemented `PPVphAB`/`PPVphBC`/`PPVphCA` registers instead of canonical `0xFFFF`).
  - Updated `StateStore.set_field()` (`pwrcell/state.py`) so readings that **both** fail physical plausibility bounds and match a vendor pseudo-sentinel for the register's point type are treated as unimplemented (`value=None`, `raw_value=None`, logged once at `DEBUG`) without emitting `WARNING` spam, while leaving valid in-bounds `65534` readings and accumulator counters untouched.
  - Added per-field state-transition deduplication in `StateStore` (`_rejected_bounds_state`) so genuine non-sentinel out-of-bounds readings log at `WARNING` only once per episode (repeating at `DEBUG` until a valid reading triggers `INFO` recovery).
  - Removed redundant `"inverter.inverter"` (Model 102, read-only) from `DEFAULT_CONFIG_PATHS` (`pwrcell/poller.py`, `config/pwrcell.example.yaml`) since it is already polled on the faster telemetry tier (`DEFAULT_FAST_PATHS`).
  - Added regression tests in `tests/test_state_and_controls.py` and `tests/test_poller.py`.

## [3.2.0] - 2026-11-15

### Added
- **Generic SunSpec Sub-Group Support (Per-Module Battery Telemetry & Nested Groups — Issue #18)**:
  - Recursively parses SunSpec sub-group metamodel definitions (`SunspecGroupDef`, `SunspecPointDef` group metadata, `ModelCatalog`, `SunspecModelDef.get_group_point()`) across all models without colliding with fixed-block register names (`pwrcell/catalog.py`).
  - Surfacing of per-battery-module telemetry from Model `804` (`lithium_ion_string_module`) and Model `64252` (`DCB105_module` warranty/module health metrics), Model `64200` (`devices` REbus directory slots including `ID`), and nested SunSpec sub-groups (`704`, `705` `Crv.Pt`, etc.).
  - Explicit group metadata (`group_name`, `group_index`, `group_path`, `group_label`) on `StateField`, `ConceptSource`, `ConceptView`, Modbus register details, and REST APIs (`pwrcell/state.py`, `pwrcell/concept.py`).
  - Polls SunSpec `battery.lithium_ion_string` (`804`) in `DEFAULT_SLOW_PATHS` and recursively extracts live `pysunspec2` sub-groups (`extract_model_groups` in `pwrcell/poller.py`) and recorded fixtures (`MockFixtureLoader` in `pwrcell/fixtures.py`, `pwrcell/client.py`).
  - Added add-on/config option `include_bulk_table_groups` (default `false`, opt-in in `config.yaml`, `pwrcell/config.py`, `pwrcell/setup_key.py`) so large curve/schedule lookup tables (`126`, `129`–`144`, `705`–`712`, `64229`–`64257`) can be enabled on demand while raw flash buffers (Model `64258` `flash_reader.sector`) are always excluded.
  - Added `group_path` traversal to `SerializedModbusClient.write_point_value()` (`pwrcell/modbus.py`) and `ControlDispatcher.write_field()` (`pwrcell/controls.py`) so writable sub-group points can be updated safely while preserving group metadata.
  - Added Web Explorer UI sub-group instance dividers (`.subgroup-divider-row`), `.badge-subgroup` pills, natural numeric name sorting (`Module 1`, `Module 2`, ..., `Module 10`), and sub-group details in the register modal (`pwrcell/ui/static/app.js`, `pwrcell/ui/static/style.css`).
- **Collapsible Sub-Group Rollup Rows in Web Explorer (`pwrcell/ui/static/index.html`, `pwrcell/ui/static/app.js`, `pwrcell/ui/static/style.css`)**:
  - Added **Roll up sub-groups** toolbar toggle (`#rollupSubgroups`, enabled by default whenever the active device exposes repeating sub-group instances) to collapse repeated SunSpec sub-group points (such as Model `804` `ModSoC` or Model `64252` `DCB105_module` metrics across all battery modules) into compact summary rows.
  - Summary rows display instance counts (e.g. `6× Modules`), a 3-state Home Assistant selection checkbox (`checked` / `indeterminate` / `unchecked`), HA exported badge (`6/6 ★`, `2/6`, `0/6`), cross-instance value range / enum summary with live SSE refresh & flash (`handleLiveFieldUpdate`), and inline group category toggling (`toggleRollupCategoryAction`).
  - Expanding a rollup opens an embedded per-instance drawer with per-instance HA checkboxes, live values, independent category toggles, `Set`/`Details`/`Copy` actions, and an inline rule-mode pill (`★ Saved as Wildcard (*)` ↔ `Saved as N Explicit Keys`).
  - Targeted searches (e.g. `"Module 3"`) automatically unroll matching concrete instances, and Optimization Plan Breakdown click-to-jump automatically expands the parent rollup and highlights the target child row.
- **Wildcard & Explicit Sub-Group Home Assistant Selection Rules (`pwrcell/catalog.py`, `pwrcell/ha.py`, `pwrcell/bridge.py`, `pwrcell/ui/routes/ha.py`, `pwrcell/optimizer.py`)**:
  - Added catalog helpers (`wildcard_group_path`, `wildcardize_group_field_key`, `is_group_wildcard_key`, `group_wildcard_matches_field_key`) supporting single-level and nested SunSpec repeating paths (e.g. `battery.lithium_ion_string.lithium_ion_string_module.*.ModSoC`, `inverter.DERVoltVar.Crv.*.Pt.*.V`).
  - Defaults to saving a canonical `*.<Point>` wildcard rule in `ha_config.yaml` when all instances in a sub-group are selected, while supporting explicit per-instance keys, automatically splitting a wildcard into remaining explicit keys when a single instance is unchecked, and auto-collapsing back to a wildcard when all explicit instances are selected.
  - Supports wildcard and per-instance Home Assistant `category_overrides` (with exact instance overrides taking precedence over wildcards), cold-start safety (`StateStore.ensure_field_definition()` never creates literal `*` `StateField` entries and preview logs `group_wildcard_awaiting_poll` until polled), HA config deduplication (`qualify_legacy_ha_config`), and accurate minimal-model solving for wildcard subgroup paths in `resolve_minimal_models_for_paths()`.
- **Sub-Group Aware Grouped Registers & Telemetry Comparison (`pwrcell/tools/recommender.py`, `pwrcell/tools/correlator.py`, `pwrcell/grouping.py`, `pwrcell/optimizer.py`, `pwrcell/ui/routes/grouping.py`)**:
  - Enforced strict sub-group hierarchy, index (`are_compatible_group_instances`), and extremum/average (`AVG` vs `MIN` vs `MAX`) isolation in `find_suggested_groupings()` so module points never cross-match across different instances or against bank-level metrics.
  - Rolled up aligned multi-instance suggestions and comparisons (with cross-instance min–max summaries, divergence propagation, one-click `Sync Sample`, wildcard approvals, and expandable per-instance breakdowns) in the **Grouped Registers & Telemetry Comparison** modal.
- **Curated Universal Default Configs & Hardened Exporters (`config/ha_default_config.yaml`, `pwrcell/data/groupings.yaml`, `pwrcell/ha.py`, `pwrcell/grouping.py`, `pwrcell/mapping.py`, `pwrcell/ui/routes/grouping.py`)**:
  - Updated `config/ha_default_config.yaml` with hybrid `.compound.` keys across inverter, battery, and PV Link devices, `pv_link.REbus_status.{I,St,V}: primary` category overrides, and `Model 804` / `Model 64252` per-module wildcards (`lithium_ion_string_module.*.Mod*`, `DCB105_module.*.PackV`), removing duplicate state/energy entries and stale `.standalone.` category overrides.
  - Kept `battery_ac_charged_energy` and `battery_ac_discharged_energy` MQTT-only in `pwrcell/data/groupings.yaml` (removing DC `WhIn`/`WhOut` Modbus registers so they no longer shadow `battery_imported_energy` / `battery_exported_energy`), and updated `export_repo_groupings()` / `generate_ha_default_config()` to keep explicit multi-source canonical mappings, preserve sub-group wildcard paths and `unit`/`member_transforms`, upgrade `.live.` keys to `.compound.`, resolve unambiguous bare `<pt>_<model>` slugs, and drop single-source, ambiguous, or stale `.standalone.` artifacts on export.
  - Updated `MappingRegistry.reload()` (`pwrcell/mapping.py`) to backfill newly added built-in group members/synonyms into persisted add-on `/data/groupings.yaml` files on upgrade while respecting `ungrouped_fields` and stripping stale DC `WhIn`/`WhOut` overlaps from `battery_ac_*`, and added `reset_mappings_to_defaults()` invoked by `POST /api/grouping/reset_defaults` to refresh runtime `groupings.yaml` from packaged defaults.
- Added unit, API, optimizer, cold-start, recommender/correlator, exporter, and Node VM frontend test suites in `tests/test_sunspec_groups.py`.

### Changed
- **Semantic Grouping & Home Assistant MQTT Discovery for Sub-Groups**:
  - Updated `group_device_fields()` (`pwrcell/optimizer.py`) to isolate sub-group points into instance-scoped concepts (`<device_type>.concept.m<model_id>_<group_path>_<point>`) so values never merge across modules/instances or into bank-level metrics.
  - Updated `pwrcell/ha.py` so sub-group entities attach to their parent `UnifiedDevice`, default to `entity_category: "diagnostic"`, preserve instance-prefixed entity labels and saved config slugs (`_resolve_standalone_or_orphan_slug`), and avoid colliding with top-level legacy discovery topics.

### Fixed
- Updated the Web Explorer header version badge (`#appVersionBadge`) and `<title>` (`pwrcell/ui/static/index.html`, `pwrcell/ui/server.py`, `pwrcell/ui/routes/devices.py`, `pwrcell/ui/static/app.js`) to dynamically reflect `pwrcell.__version__` (`v3.2.0`) instead of hardcoded `v3.0`.
- Cleared invalid unit/scale-factor metadata on SunSpec Model `804` `ModCellVMinCell` and defaulted `%` units on Model `64252` `DCB105_module` `SOC`/`SOH` points in `pwrcell/catalog.py`.

## [3.1.16] - 2026-11-15

### Fixed
- **Battery SoC/SoH Retained Discovery Topic Collision & Model Alias Grouping (Issue #17)**:
  - Disambiguated raw Modbus discovery `object_id`/`sub_key` (`generate_discovery_payload` in `pwrcell/ha.py`) when a raw point's trailing path collides with a compound concept ID on the same device type (e.g., Model 802 `battery.battery.SoC` -> `m802_soc` and `battery.battery.SoH` -> `m802_soh`), preventing suppressed Model 802 member clears from wiping retained `battery_soc/config` and `battery_soh/config` discovery payloads on the MQTT broker.
  - Hardened `HomeAssistantBridge.publish_discovery()` and `_on_compound_update()` (`pwrcell/bridge.py`) to defer all suppressed-member and legacy retained `""` clears until after active discovery and state topics are registered, never clearing any topic claimed by an active entity.
  - Updated `ensure_selected_field_definitions()` (`pwrcell/ha.py`) to pre-populate only a single primary non-excluded candidate on cold start when a selected compound has zero polled members yet, avoiding unnecessary synthetic placeholder raw fields.
  - Expanded `model_<id>` aliases to canonical SunSpec catalog model names at `MappingRegistry.reload()` (`pwrcell/mapping.py`), added explicit canonical SunSpec model keys (including `inverter.REbus_status.St`, `inverter.inverter.St`, `inverter.DERMeasureAC.InvSt`, and `invst` synonym in `inverter_state`) to `pwrcell/data/groupings.yaml`, and preserved `unit` when serializing `battery_soc` in `save_mappings()`.

### Added
- **Collision-Avoidance & Alias-Expansion Diagnostics and Regression Tests**:
  - Added `DEBUG` logging in `pwrcell/ha.py`, `pwrcell/bridge.py`, and `pwrcell/mapping.py`, plus 4 regression tests in `tests/test_issue_17_ha_config.py`.

## [3.1.15] - 2026-11-15

### Fixed
- **Home Assistant Selection, Config Migration & MQTT Discovery Preview Sync (Issue #17)**:
  - Fixed Web UI selection helpers (`getCompoundKeyForItem`, `isFieldSelected`, `toggleHaSelection`, `btnDeselectAll`, `btnApplySameType`, and `compoundKeyByRaw` lookup) in `pwrcell/ui/static/app.js` so standalone Unified View rows preserve their real raw keys instead of fabricating invalid `.compound.` keys, and compound selections/deselections cleanly manage member keys via `member_keys` exported by `ConceptView.to_dict()` (`pwrcell/concept.py`).
  - Updated `btnPreviewHA` in `pwrcell/ui/static/app.js` and `/api/ha/preview` in `pwrcell/ui/routes/ha.py` to support live `POST` previews of unsaved UI selections and category overrides alongside `GET` previews, while pre-populating unpolled MQTT/Modbus definitions from `mqtt_telemetry.yaml` (`StateStore.ensure_field_definition` in `pwrcell/state.py`).
  - Fixed `StateStore.get_compound_view()` in `pwrcell/state.py` so Modbus-only `inverter_state` views preserve `ha_device_class="enum"`.
  - Updated `pwrcell/ha.py` (`qualify_legacy_ha_config`, `_remap_concept_key`, and shared `ensure_selected_field_definitions`, `collect_compound_member_keys`, `is_raw_field_suppressed` helpers) and `pwrcell/bridge.py` to repair orphaned `.standalone.`/invalid `.compound.` keys, respect per-device ungrouped exclusions when remapping or suppressing raw member entities, and keep `ha_config.yaml` vs preview/bridge discovery aligned.
  - Updated `pwrcell/optimizer.py` (`group_device_fields`, `resolve_minimal_models_for_paths`) and `pwrcell/ui/routes/devices.py` to honor both `.compound.` and `.concept.` selections when resolving optimal Modbus polling models.
  - Updated `pwrcell/mapping.py` (`load_mappings`, `save_mappings`, `TelemetryMappingDef.member_transforms`), added `battery.lithium_ion_string.SoC` to `battery_soc` in `pwrcell/data/groupings.yaml`, and removed stale/redundant entries from `config/ha_default_config.yaml`.

### Added
- **Expanded `DEBUG`-Level Diagnostic Logging & Regression Tests**:
  - Added detailed `DEBUG` logging across `pwrcell/ha.py`, `pwrcell/state.py`, `pwrcell/ui/routes/ha.py` (save diffs and unmatched preview keys), `pwrcell/bridge.py` (reload diffs and skipped/unmatched keys), `pwrcell/mapping.py`, and `pwrcell/ui/static/app.js` (`console.debug` selection trace) to aid diagnostics.
  - Added regression tests in `tests/test_issue_17_ha_config.py` (including Node-executed verification of `app.js` helpers and `assertLogs` debug-logging assertions) and updated default config assertions in `tests/test_ui.py`.

## [3.1.14] - 2026-11-14

### Fixed
- **Custom Concepts `TelemetryMappingDef` Initialization Error (Issue #16)**:
  - Removed the invalid `name` keyword argument when constructing `TelemetryMappingDef` for custom concepts in `StateStore.get_compound_view` (`pwrcell/state.py`), which caused `TypeError: TelemetryMappingDef.__init__() got an unexpected keyword argument 'name'` and prevented UI field loading and MQTT discovery/updates whenever `custom_concepts` were present.
  - Also added fallback support for `unit` alongside `units` in custom concept metadata.
  - Added regression test `test_get_compound_view_with_custom_concept` in `tests/test_compound_and_mapping.py`.

## [3.1.13] - 2026-11-13

### Fixed
- **MQTT Retained State Continuity on Home Assistant Reconnects**:
  - Updated `HomeAssistantBridge._on_field_update` in `pwrcell/bridge.py` to publish live raw field state updates with `retain=True` (matching `publish_discovery` and `_on_compound_update`).
  - Prevents Mosquitto from holding stale retained `state_topic` payloads between discovery runs, eliminating false `total_increasing` counter reset spikes in Home Assistant Energy statistics when Home Assistant restarts or reloads MQTT.
  - Added unit test `test_on_field_update_retains_state_to_prevent_stale_broker_values` in `tests/test_bridge.py`.

## [3.1.12] - 2026-11-12

### Fixed
- **PV Link Energy Counter Continuity & Negative Solar Statistics**:
  - Replaced high-water mark clamping with **Cumulative Baseline Offset Tracking** in `StateStore._process_counter_monotonicity`. When a PV Link suffers overnight uncommitted RAM loss at brownout (e.g. dropping 5–250 Wh from dusk to dawn flash recovery), the lost delta is automatically converted into a persistent cumulative offset after 2-poll debounce.
  - **Zero Masking of Morning Solar Generation**: Unlike high-water mark freezing, every watt-hour produced at sunrise is immediately added to the offset baseline and published to Home Assistant, completely eliminating morning generation masking.
  - **No Negative Energy Deltas in Home Assistant**: Prevents Home Assistant long-term statistics compiler from recording negative hourly solar production bars on the Energy Dashboard.
  - Added debounced zero-reset handling (requiring 3 consecutive readings of $\le 1\text{ Wh}$) so clean daily session resets on PV Links or meter rollovers are passed through cleanly without transient glitch vulnerability.
  - Persisted cumulative offsets to `.monotonic_offsets.json` in `data_dir()` so continuity survives add-on restarts.
  - Always suppress corrupt/invalid negative energy readings on cumulative counters.
  - Added comprehensive unit tests in `tests/test_state_and_controls.py` verifying brownout drop offset calculation, unmasked morning generation reporting, and restart persistence.

## [3.1.11] - 2026-11-12

### Changed
- **Management UI Documentation Streamlining**:
  - Removed obsolete ASCII art diagram mockups replaced by screenshots in `docs/management_ui.md`.
  - Streamlined documentation for clarity and conciseness, replacing dense prose with structured tables and crisp operational references.

## [3.1.10] - 2026-11-12

### Added
- **Web Explorer UI Screenshots in Documentation**:
  - Captured actual screenshots from the live Web Explorer in mock simulation mode (`python main.py explore --mock`).
  - Added visual references in `docs/images/` and embedded into `docs/management_ui.md`:
    - `ui_overview_unified.png`: Primary overview dashboard showing live header chips, device tree, minimal polling plan, and unified grid.
    - `ui_rescan_discovery.png`: Device discovery modal showing slave ID range and cache purge option.
    - `ui_all_registers_raw.png`: Raw register map view showing all SunSpec models, scale factors, and wire points.
    - `ui_modbus_details.png`: Modbus Register Definition inspector modal detailing register offsets, types, and scale factor exponents.
    - `ui_telemetry_comparison.png`: Telemetry comparison modal displaying agreement status, discrepancy tabs, and Sync Sample controls.
    - `ui_safety_policy.png`: Blocked Modbus mutation fields modal illustrating safety-protected registers.
    - `ui_mqtt_preview.png`: Home Assistant MQTT discovery JSON preview modal.

## [3.1.9] - 2026-11-12

### Added
- **Management UI (Web Explorer) Technical Documentation**:
  - Added comprehensive [Web Explorer Technical Guide](docs/management_ui.md) in `docs/management_ui.md` targeting technical users, developers, and energy systems engineers.
  - Documented complete architecture (dual-stream MQTT/Modbus ingestion, SSE streaming, weighted set-cover minimal polling optimizer).
  - Detailed guides for all UI components: Header telemetry & system mode control, hardware discovery tree, Unified Semantic vs. Raw register views, minimal model solver with manual source pinning, Modbus register inspector, writable setpoints/bounds validation, telemetry discrepancy analysis & polarity resolution, safety policy enforcement for hazardous registers, and Home Assistant MQTT Discovery management.
  - Added cross-links from `README.md` and `DOCS.md`.

## [3.1.8] - 2026-11-12

### Fixed
- **Grouped Entity HA Discovery Synchronization & Default Config**:
  - In `config/ha_default_config.yaml`: Updated default entity seed configuration to specify canonical compound entity keys (`pv_link.compound.accumulated_energy`, `pv_link.compound.rebus_power`, `pv_link.compound.device_temperature`, `inverter.compound.rebus_voltage`, `battery.compound.max_cell_voltage`, `battery.compound.min_cell_voltage`, `battery.compound.battery_power`, `battery.compound.battery_soc`, `battery.compound.battery_ac_charged_energy`, `battery.compound.battery_ac_discharged_energy`, `inverter.compound.inverter_output_energy`, `inverter.compound.solar_power`, `inverter.compound.system_mode`).
  - In `pwrcell/bridge.py` and `pwrcell/ui/routes/ha.py`: Ensured `/api/ha/preview` and `publish_discovery()` suppress all raw members whose compound view is active, including checking `MappingRegistry.get_raw_to_compound_map()` and mapping candidates to prevent raw register leakage.
- **Inverter Grid Imported Energy Grouping**:
  - In `pwrcell/data/groupings.yaml`: Added `inverter.REbus_exp.Whin`, `inverter.model_64204.Whin`, and `inverter.model_64204.WhIn` (SunSpec Model 64204 REbus Export/Import model registers) to `grid_imported_energy`, grouping them cleanly and eliminating raw entity leakage (`rebus_exp_whin`).
- **Elimination of `_None` Suffixes on Standalone Push Telemetry**:
  - In `pwrcell/optimizer.py` & `pwrcell/ha.py`: Fixed standalone concept key generation for unmapped push telemetry fields where `model_id` is None, generating clean identifiers (e.g. `load_power_w`, `load_imported_energy_wh`, `solar_generation_energy_wh`, `inverter_max_power_w`) without appending malformed `_None` suffixes.

## [3.1.7] - 2026-11-11

### Fixed
- **Inverter Operational State Reporting & Enum Options**: Fixed issue where `Inverter Operational State` was not showing or updating in Home Assistant.
  - In `pwrcell/data/groupings.yaml`: Reordered Modbus candidates for `inverter_state` to prioritize `inverter.model_64207.St` (which contains full Generac SunSpec REbus state symbols) ahead of vendor-specific raw integer points (`StVnd`). Removed obsolete `inverter.concept.inverter_state` from `ungrouped_fields`.
  - In `pwrcell/state.py`: Guaranteed that `inverter_state` compound views always resolve `ha_device_class = "enum"` with complete REbus status symbols (`GRID_CONNECTED`, `STANDBY`, etc.), and automatically convert raw integer codes (`2080`) or numeric strings to their canonical enum symbol name across Modbus, MQTT, and latest values so Home Assistant never receives invalid raw integer states for enum sensors.
  - In `pwrcell/bridge.py`: Set `retain=True` for compound state updates in `_on_compound_update()`, preventing Home Assistant restarts or reconnects from falling back to stale or uninitialized state.
- **System Operating Mode Option Deduplication & Normalization**:
  - In `pwrcell/controls.py`: Added `get_canonical_system_operating_modes()` to provide deduplicated system modes without synonym collisions. Canonicalized written mode names in `set_system_mode()` so that aliases (e.g. `GRID_CONNECT`, `FULL_EXPORT`, `ARBITRAGE`) map to canonical SunSpec names (`GRID_TIE`, `SELL`, `REMOTE_ARBITRAGE`).
  - In `pwrcell/state.py`: Populated `system_mode` compound view options with canonical modes and normalized alias values in `get_compound_view()`, eliminating duplicate synonyms in the Home Assistant select dropdown.
- **Web Explorer Write Modal Enum Dropdown**:
  - In `pwrcell/ui/static/app.js`: Updated `openWriteModal()` and `lookupEnumSymbol()` to detect enum fields via `field.bounds.symbols` and `field.ha_options` in addition to direct `field.symbols`, enabling dropdown selection for merged/compound enum fields like `System Operating Mode` instead of rendering a plain text input.

## [3.1.6] - 2026-11-11

### Fixed
- **Group Selection Generating Multiple HA Entities**: Fixed issue where selecting a single group row in the Web UI (e.g. "Inverter Operational State") resulted in multiple entities in Home Assistant (`sensor.pwrcell_inverter_14e9_inverter_operational_state` and `sensor.pwrcell_inverter_14e9_inverter_state_name`).
  - In `pwrcell/ui/static/app.js`: Updated `toggleHaSelection` and peer device application to only select the compound key (`<SN>:<dev>.compound.<concept>`) for grouped items, never the raw member source keys (`f.active_source_key` or `f.key`), and to clear any individual member selections upon group selection.
  - In `pwrcell/ha.py`: Updated `_LEGACY_CONCEPT_REMAP` to map `inverter.concept.inverter_state` and legacy `inverter.live.inverter_state_name` to `inverter.compound.inverter_state`, and `battery.concept.battery_soh` to `battery.compound.battery_soh`.
  - In `pwrcell/bridge.py`: Expanded member suppression in `publish_discovery()` and `_is_field_suppressed_by_compound()` to include all mapping candidate members (`m.mqtt_fields` and `m.modbus_fields`), ensuring secondary MQTT and Modbus points (like `inverter.live.inverter_state_name`) are properly suppressed and removed from Home Assistant.
  - In `pwrcell/data/groupings.yaml` & `pwrcell/state.py`: Prioritized `inverter.live.inverter_state_name` over numeric `inverter.live.inverter_state` in `inverter_state` mapping, and mapped MQTT `ha_hint.options` and `ha_hint.device_class` onto the compound view, so the unified compound sensor publishes the friendly enum string (e.g. `GRID_CONNECTED`) with declared options in Home Assistant.

## [3.1.5] - 2026-11-10

### Fixed
- **Combined Sensor Jitter & Out-of-Order Delivery**: Fixed combined sensors (MQTT + Modbus) updating from both sources simultaneously. When MQTT is selected for a grouped concept, Modbus updates for that concept are ignored—preventing newer Modbus poll timestamps from overwriting MQTT push telemetry in `StateStore.get_compound_view()`, and suppressing Modbus-triggered compound change dispatches in `set_field()` and `HomeAssistantBridge._on_compound_update()`.
- **System Mode Control Synchronization**: Ensured `set_system_mode()` updates both the Modbus register and the live push telemetry state (`inverter.live.system_mode`) so compound views reflect control mutations immediately without waiting for the next telemetry cycle.
- **Preferred Source Custom Groupings Support**: Added `preferred_sources` configuration support in `pwrcell/grouping.py` for persistent user pinning of sources via `custom_groupings.yaml`.

## [3.1.4] - 2026-11-10

### Fixed
- **Multi-Device Control Dispatch Scoping**: Updated `ControlDispatcher.write_field()` to accept `device_sn` (and parse `<SN>:<field>` prefixes), scoping writes correctly on multi-device systems (e.g. secondary PV Links and multi-battery setups) instead of always defaulting to `devs[0]`.
- **Compound and Concept Control Writes**: Normalized `.concept.` keys to `.compound.` in `ControlDispatcher.write_field()`, scoped compound views to `device_sn`, and prioritized writable Modbus candidates.
- **Home Assistant Command Dispatch Device Context**: Passed device serial numbers through `HomeAssistantBridge._on_message` and `_execute_command_async` into control writes.
- **Safety Blocked Mutation Compound View Audit**: Updated `get_blocked_mutation_fields()` to inspect compound views via `StateStore.get_compound_views()` instead of the nonexistent `.compound_views` attribute.
- **HA Config File I/O Caching**: Added `st_mtime`-based caching with automatic cache invalidation on save for `load_ha_config()` and `load_ha_category_overrides()` in `pwrcell/ha.py`.
- **Category Override Isolation & Deduplication**: Removed unscoped `pt_name_model_id` match candidate in `get_effective_ha_category()` and removed unscoped bare keys from `config/ha_default_config.yaml` to prevent cross-device category bleeding.
- **Internal MQTT Tunnel Port Update**: Hardened `MqttClient` reconnect handling on SSH tunnel reconnect to update `client._port`.
- **Web UI Home Assistant Entity Preview**: Updated unified row preview in Web Explorer JavaScript to generate accurate `haEntityId` using device serial number and platform.
- **Correlator Shim Cleanup**: Re-exported `ComparisonResultRow` properly from `pwrcell/correlator.py` and removed unused shadowed import from `pwrcell/tools/correlator.py`.

## [3.1.3] - 2026-11-10

### Fixed
- **Multi-Device Compound Views**: Resolved single-device lookup collision (`devs[0]`) in `StateStore.get_compound_view()` by adding `device_sn` scoping, enabling compound sensors on secondary PV Links and multi-battery installations.
- **Null Modbus Clobbering Valid Telemetry**: Ensured that polling an unimplemented or sentinel register (returning `None`) does not overwrite valid push telemetry in `get_compound_view()`.
- **Compound View Selection & Remapping**: Updated `qualify_legacy_ha_config()` to remap recognized `<dev>.concept.<id>` keys to `<dev>.compound.<id>` instead of discarding them, and aligned `is_field_selected()` to match `.concept.` and `.compound.` aliases.
- **HA Discovery Race Condition & Duplicate Sensors**: Pre-populated field definitions before compound discovery step in `HomeAssistantBridge.publish_discovery()`, and unpublished raw member sensor discovery topics when compound views are published dynamically.
- **Preview Discovery Filtering**: Updated `/api/ha/preview` to filter out raw member fields suppressed by active compound views.
- **Ungrouping Suppression & Compound Link Refresh**: Added `refresh_compound_links()` to `StateStore` and filtered excluded fields from `modbus_candidates` so ungrouped fields are not hidden from Home Assistant.
- **Dead Code Cleanup in Compound View**: Fixed unreachable dead code assigning `c_view.ha_category` and passed serial number instead of device object.
- **Web UI Compound Key Selection**: Fixed `isFieldSelected()`, `toggleHaSelection()`, and `btnDeselectAll` in Web Explorer JavaScript to properly track, toggle, and clear `.compound.` entity keys.
- **Missing Solar Generation Power Concept**: Restored `solar_power` concept in `groupings.yaml` and removed `battery.live.state_of_health` from `ungrouped_fields`.
- **Default Config Deduplication**: Removed redundant duplicate sibling member keys from `config/ha_default_config.yaml` and `config/ha_config.yaml`.

## [3.1.2] - 2026-11-10

### Added
- Force full device re-scan option and cache clearing in Web Explorer UI:
  - Added Re-scan button and modal to UI with configurable Start and End slave IDs.
  - Added "Force full re-scan (delete existing device cache)" option.
  - Added "Scan for Devices" call-to-action button when the device sidebar is empty.
  - Added `DeviceConfig.delete()` method to safely remove cached `devices.yaml`.
  - Added `SerializedModbusClient.clear_devices()` to clear cached SunSpec client instances.
  - Added `clear_cache` parameter support in `client.rescan_devices()` and `POST /api/devices/rescan`.

## [3.1.1] - 2026-11-07

### Added
- Added "My Home Assistant" one-click add-on repository install badge to `DOCS.md` and `README.md`.

### Fixed
- Fixed Modbus device discovery scan aborting on duplicate unit serial numbers (#14). Defaulted `stop_on_duplicate_serial` to `False` and added duplicate threshold termination to avoid missing devices at higher slave IDs.

## [3.1.0] - 2026-10-27

### Added
- Full functional release of Generac PWRcell SunSpec Gateway and Home Assistant Add-on.
- Integrated Web Explorer accessible via Home Assistant Ingress.
- Native Home Assistant MQTT Auto-Discovery with entity categories (diagnostic, configuration).
- Operating mode control (`SELF_SUPPLY`, `CLEAN_BACKUP`, `PRIORITY_BACKUP`, etc.) with validation.
- Automatic SSH tunneling to Generac Beacon.
- Modbus register and push telemetry inspection and comparison.

## [3.0.18] - 2026-10-27

### Fixed
- Fixed Home Assistant diagnostic category matching and multi-device synchronization.

## [3.0.17] - 2026-10-27

### Security
- Protected inverter zero export settings (`ZExp` and `ZExpLim`) from mutation.

## [3.0.16] - 2026-10-27

### Added
- Safety blocked mutation fields configuration (`config/blocked_fields.yaml`).
- Groupings and Home Assistant default config exports.

## [3.0.15] - 2026-10-27

### Added
- Home Assistant entity category controls and UI table badges.
