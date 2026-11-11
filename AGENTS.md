# Agent Guidelines & Repository Instructions

This document provides instructions and protocols for AI assistants and automated tools working on the **pwrcell_sunspec** repository.

---

## 🚨 Mandatory Code Update Protocol: Release Version & Release Notes

Whenever you make updates, modifications, or additions to code in this repository (features, bug fixes, enhancements, or refactors), you **MUST** always perform the following two steps before concluding the task:

### 1. Update the Release Version (Semantic Versioning)

Adhere strictly to [Semantic Versioning (SemVer)](https://semver.org/):
- **PATCH** (`X.Y.Z` -> `X.Y.(Z+1)`): Bug fixes, small patches, internal refactoring, or minor non-breaking enhancements.
- **MINOR** (`X.Y.Z` -> `X.(Y+1).0`): New features, backward-compatible additions, new endpoints, or newly supported devices/models.
- **MAJOR** (`X.Y.Z` -> `(X+1).0.0`): Breaking changes, schema changes incompatible with prior versions, or major architectural shifts.

**Version Files (Both MUST Be Updated in Sync):**
1. [config.yaml](file:///Users/edalquist/projects/pwrcell_sunspec/config.yaml):
   ```yaml
   version: "X.Y.Z"
   ```
2. [pwrcell/__init__.py](file:///Users/edalquist/projects/pwrcell_sunspec/pwrcell/__init__.py):
   ```python
   __version__ = "X.Y.Z"
   ```

> [!IMPORTANT]
> Both `config.yaml` and `pwrcell/__init__.py` must always have the exact same version string. Never update one without the other.

---

### 2. Update Release Notes in `CHANGELOG.md`

All user-visible and technical changes must be documented in [CHANGELOG.md](file:///Users/edalquist/projects/pwrcell_sunspec/CHANGELOG.md) following the [Keep a Changelog](https://keepachangelog.com/) format. Home Assistant Supervisor displays this file directly in the Add-on Store changelog tab.

**Format:**
```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- Description of new features, options, or endpoints.

### Changed
- Description of changes in existing functionality.

### Fixed
- Description of bugs or issues resolved.

### Removed
- Description of features or deprecated capabilities removed.

### Security
- Vulnerability or security improvements.
```

- Add the new version block directly below the header introduction and above previous version entries.
- Use the current date in ISO format (`YYYY-MM-DD`).
- Use clear bullet points explaining what changed, which components/files were affected, and any user-facing impacts or resolved issue numbers.

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

Before finalizing changes and version bumps:
1. Run relevant unit tests using Python in `.venv`:
   ```bash
   .venv/bin/python3 -m unittest discover tests
   ```
   Or for individual test files:
   ```bash
   .venv/bin/python3 -m unittest tests/test_<module>.py
   ```
2. Verify both version definitions match:
   - `grep 'version:' config.yaml`
   - `grep '__version__' pwrcell/__init__.py`
3. Verify that `CHANGELOG.md` contains an entry corresponding to the new version.
