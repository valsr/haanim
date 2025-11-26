# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- UV package management integration
- Comprehensive `pyproject.toml` with all dependencies and tool configurations
- `UV_GUIDE.md` documentation for UV usage
- Test suite structure with pytest
- **GitLab CI pipeline** with multi-version testing, linting, and coverage reporting
- GitHub Actions CI workflow (alternative for GitHub users)
- Make commands for UV operations (`make install`, `make dev`, `make test`, etc.)
- `.python-version` file for Python version management
- **VS Code tasks and debug configurations** for one-click development
  - Start Home Assistant with automatic browser opening
  - Run and Debug configurations
  - Testing and linting tasks
  - Container management tasks

### Changed

- Updated README with UV setup instructions
- Updated CONTRIBUTING guide with UV workflows
- Enhanced Makefile with UV-based commands
- Updated `.gitignore` to include UV-specific entries
- **Migrated CI pipeline to GitLab CI** as primary platform

### Infrastructure

- Moved from manual dependency management to UV
- Added automated testing and linting in GitLab CI
- Standardized development workflow with Make commands
- Configured coverage reporting with GitLab artifacts
- Added dependency caching for faster CI builds
- **Integrated VS Code development workflow** with tasks and debug configs

## [0.1.0] - 2025-11-25

### Added
- Initial release
- Basic HAAnim integration for Home Assistant
