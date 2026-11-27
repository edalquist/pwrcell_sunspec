# Agent Guidelines & Repository Instructions

This document provides instructions and protocols for AI assistants and automated tools working on the **pwrcell_sunspec** repository.

---

## Release Management (`release-please`)

Releases, version bumps, release notes in [CHANGELOG.md](file:///Users/edalquist/projects/pwrcell_sunspec/CHANGELOG.md), and Git tags (`vX.Y.Z`) are managed **exclusively** by `release-please` ([.github/workflows/release-please.yml](file:///Users/edalquist/projects/pwrcell_sunspec/.github/workflows/release-please.yml) and [release-please-config.json](file:///Users/edalquist/projects/pwrcell_sunspec/release-please-config.json)).

### 1. Do NOT Manually Bump Versions or Edit `CHANGELOG.md`

- **Never** manually bump versions in [config.yaml](file:///Users/edalquist/projects/pwrcell_sunspec/config.yaml), [pwrcell/__init__.py](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/__init__.py), or [.release-please-manifest.json](file:///Users/edalquist/projects/pwrcell_sunspec/.release-please-manifest.json), and **never** manually add release sections to [CHANGELOG.md](file:///Users/edalquist/projects/pwrcell_sunspec/CHANGELOG.md) in regular feature, fix, or refactor commits.
- Manually bumping `.release-please-manifest.json` without a corresponding `vX.Y.Z` Git tag/release breaks `release-please`'s tag boundary lookup, causing cumulative changelogs across the entire repo history and double-bumped versions.
- Preserve the `# x-release-please-version` inline comments on `version:` in [config.yaml](file:///Users/edalquist/projects/pwrcell_sunspec/config.yaml) and `__version__ =` in [pwrcell/__init__.py](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/__init__.py) so `release-please` can keep all version files synchronized automatically when opening and merging a Release PR.

### 2. Use Conventional Commits

Always format commit subjects using [Conventional Commits](https://www.conventionalcommits.org/) so `release-please` computes the right [Semantic Versioning (SemVer)](https://semver.org/) bump and changelog section automatically:

- **`feat:`** or **`feat(<scope>):`** -> **MINOR** (`X.(Y+1).0`), listed under **Added**.
- **`fix:`** or **`fix(<scope>):`** -> **PATCH** (`X.Y.(Z+1)`), listed under **Fixed**.
- **`feat!:`**, **`fix!:`**, or a **`BREAKING CHANGE:`** footer -> **MAJOR** (`(X+1).0.0`).
- **`perf:`**, **`refactor:`**, **`revert:`** -> listed under **Changed** (no MINOR/MAJOR bump on their own).
- **`docs:`**, **`chore:`**, **`ci:`**, **`test:`** -> hidden from release notes.

> [!IMPORTANT]
> `config.yaml`, `pwrcell/__init__.py`, and `.release-please-manifest.json` must always have the exact same version string, and `CHANGELOG.md` must contain an entry for that version (enforced by CI's `Version & Changelog Sync` job). Leaving these files untouched on feature/fix commits keeps them synchronized at the latest released version until `release-please` merges the next Release PR.

---

## Repository Architecture & Core Files

- **`config.yaml`**: Home Assistant Add-on configuration manifest (defines add-on version, name, options, schema, and ingress).
- **`pwrcell/`**: Main Python package:
  - `pwrcell/__init__.py`: Package entry and version identifier (`__version__`).
  - `pwrcell/client.py`: High-level client coordinating Modbus, SSH tunnel, MQTT broker, and state store.
  - `pwrcell/modbus.py`: SunSpec Modbus TCP client and slave scanning logic.
  - `pwrcell/mqtt.py`: MQTT Discovery publishing to Home Assistant and internal telemetry bus.
  - `pwrcell/state.py`: Unified device and state storage.
  - `pwrcell/ui/`: Embedded Web Explorer (Flask web app and vanilla JS frontend).
- **`CHANGELOG.md`**: Project changelog and Home Assistant Add-on release notes.
- **`DOCS.md`**: Add-on user documentation rendered inside Home Assistant Supervisor.
- **`Dockerfile`**: Container definition for building the add-on image.
- **`tests/`**: Unit test suite.

---

## Testing & Verification

Before finalizing changes:
1. Run relevant unit tests using Python in `.venv`:
   ```bash
   .venv/bin/python3 -m unittest discover tests
   ```
   Or for individual test files:
   ```bash
   .venv/bin/python3 -m unittest tests/test_<module>.py
   ```
2. Verify that all three version definitions remain synchronized at the current released version (and have not drifted from `CHANGELOG.md`):
   - `grep 'version:' config.yaml`
   - `grep '__version__' pwrcell/__init__.py`
   - `cat .release-please-manifest.json`
   - `head -n 15 CHANGELOG.md`
