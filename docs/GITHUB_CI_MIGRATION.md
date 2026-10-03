# GitHub CI Migration Summary

## Overview

The HAAnim project has migrated from GitLab (source hosting + GitLab CI) to **GitHub**, with **GitHub Actions** as the primary continuous integration platform. The pipeline leverages UV for fast dependency management and includes comprehensive testing and quality checks.

## What Was Done

### New/Updated Files

1. **`.github/workflows/ci.yml`** - Comprehensive GitHub Actions pipeline
   - Replaces `.gitlab-ci.yml` (removed)
   - Matrix test job across Python 3.12 and 3.13
   - Lint job (Black, Pylint, Flake8, Mypy)
   - Secret detection job (Gitleaks)
   - Coverage uploaded to Codecov and stored as a workflow artifact

2. **`GITHUB_CI_GUIDE.md`** - Complete GitHub Actions documentation
   - Pipeline structure and jobs
   - Job descriptions and configurations
   - Troubleshooting guide
   - Best practices

3. **`GITHUB_CI_QUICKREF.md`** - Quick reference for day-to-day use

4. **Updated Documentation**
   - `README.md` - Swapped badges and links to GitHub, updated CI section
   - `CONTRIBUTING.md` - Clone URLs and "merge request" → "pull request" terminology
   - `UV_GUIDE.md`, `UV_MIGRATION.md` - Updated CI sections for GitHub Actions
   - `pyproject.toml`, `manifest.json` - Repository/documentation/issue URLs
   - `CHANGELOG.md` - Documented the migration

### Pipeline Features

#### Jobs
- `test` - Run pytest with coverage across the Python version matrix
- `lint` - Code quality checks (Black required, others informational)
- `secret-detection` - Gitleaks secret scanning

## Key Features

### 🚀 Performance
- **Parallel execution**: `test`, `lint`, and `secret-detection` run as separate jobs
- **UV speed**: 10-100x faster than pip for dependency installation

### 📊 Coverage Reporting
- Coverage uploaded to Codecov on every run
- HTML and XML coverage reports stored as workflow artifacts (30 days)

### ✅ Quality Gates
- Black formatting is **required** (blocks the job)
- Tests must pass (blocks the job)
- Other linters are informational

## How to Use

### Automatic Execution
The pipeline runs automatically on:
- Every push to `main`, `master`, or `develop`
- Every pull request targeting those branches

### Manual Execution
Re-run a workflow from the **Actions** tab → select the run → **Re-run jobs**.

### Viewing Results

**Pipeline Overview:**
- Go to the **Actions** tab
- Click a run to see all job statuses
- Green check = passed, red X = failed

**Coverage:**
- Shown via the Codecov check on the pull request
- Available as a workflow artifact (`coverage-py*`)

## Local Testing

Reproduce CI results locally:

```bash
# Run tests like CI
uv run pytest --cov=custom_components/haanim --cov-report=term --cov-report=xml --cov-report=html

# Check formatting
uv run black --check --line-length 110 custom_components/haanim/

# Run linters
uv run pylint custom_components/haanim/
uv run flake8 custom_components/haanim/
uv run mypy custom_components/haanim/

# Or use Make shortcuts
make test    # Tests with coverage
make format  # Fix formatting
make lint    # Run all linters
make check   # Run all checks
```

## Comparison: GitHub Actions vs GitLab CI

| Feature     | GitHub Actions              | GitLab CI (retired)      |
| ----------- | ---------------------------- | ------------------------ |
| Status      | **Primary** (configured)     | Retired                  |
| File        | `.github/workflows/ci.yml`   | `.gitlab-ci.yml` (removed) |
| Coverage    | Via Codecov                  | Native GitLab feature    |
| Artifacts   | GitHub Actions artifacts     | GitLab Artifacts         |
| Secret scan | Gitleaks Action              | GitLab Secret-Detection template |

## Next Steps

1. ✅ Repository origin moved to `git@github.com:valsr/haanim.git`
2. ✅ `.gitlab-ci.yml` removed
3. ✅ GitHub Actions workflow updated for parity (matrix testing, secret detection)
4. ✅ Documentation and links updated across the repo
5. 📋 Configure branch protection to require the `test` and `lint` checks
6. 📋 Add a `CODECOV_TOKEN` repository secret if the repo is private

## Resources

- [GITHUB_CI_GUIDE.md](GITHUB_CI_GUIDE.md) - Detailed pipeline documentation
- [UV_GUIDE.md](UV_GUIDE.md) - UV package management guide
- [ci.yml](../.github/workflows/ci.yml) - Pipeline configuration
- [GitHub Actions Docs](https://docs.github.com/en/actions)

## Summary

✅ **GitHub Actions is now the CI platform for HAAnim, hosted on GitHub**

Every push and pull request triggers:
- Multi-version testing
- Code quality checks
- Coverage reporting
- Secret scanning

All with fast execution thanks to UV.

---

**Migration Completed**: 2026-07-08
**Pipeline Status**: Active
**Platform**: GitHub Actions
