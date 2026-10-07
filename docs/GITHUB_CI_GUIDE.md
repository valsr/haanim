# GitHub Actions CI Configuration Guide

This document explains the GitHub Actions CI/CD pipeline configuration for the HAAnim project.

## Overview

The CI pipeline is configured in `.github/workflows/ci.yml` and uses UV for fast, reliable Python package management. The pipeline runs automatically on every push and pull request.

## Pipeline Structure

### Jobs

1. **test** - Run pytest on multiple Python versions (matrix)
2. **lint** - Code quality checks
3. **secret-detection** - Security scanning

#### Test Job

**`test`**
- Runs on a Python version matrix (3.12, 3.13)
- Executes pytest with coverage reporting
- Uploads coverage to Codecov
- Generates coverage artifacts in multiple formats

```yaml
test:
  strategy:
    matrix:
      python-version: ['3.12', '3.13']
  steps:
    - run: uv run pytest --cov=custom_components/haanim --cov-report=xml
```

**Artifacts Generated:**
- `coverage.xml` - Cobertura format
- `htmlcov/` - HTML coverage report
- Available for 30 days

#### Lint Job

**`lint`** runs the following checks in sequence:

- **Black** - Code Formatting Check
  - Verifies code follows Black formatting rules
  - Line length: 110 characters
  - **Fails the pipeline** if code is not formatted
- **Pylint** - Static Code Analysis (informational, does not fail the job)
- **Flake8** - PEP 8 style checking (informational, does not fail the job)
- **Mypy** - Static type checking (informational, does not fail the job)

#### Security Job

**`secret-detection`**
- Scans for accidentally committed secrets
- Uses [Gitleaks](https://github.com/gitleaks/gitleaks) via `gitleaks/gitleaks-action`
- Runs on every pipeline

## Configuration Details

### Triggers

```yaml
on:
  push:
    branches: [main, master, develop]
  pull_request:
    branches: [main, master, develop]
```

### Coverage Reporting

Coverage is uploaded to [Codecov](https://about.codecov.io/) and generated locally as:

1. **Terminal Output** - Immediate feedback in job logs
2. **XML (Cobertura)** - Consumed by Codecov
3. **HTML** - Detailed browseable report, uploaded as a workflow artifact

## Running Locally

To reproduce CI results locally:

```bash
# Run tests like CI does
uv run pytest --cov=custom_components/haanim --cov-report=term --cov-report=xml --cov-report=html

# Run Black check
uv run black --check --line-length 110 custom_components/haanim/

# Run Pylint
uv run pylint custom_components/haanim/

# Run Flake8
uv run flake8 custom_components/haanim/

# Run Mypy
uv run mypy custom_components/haanim/

# Or use Make commands
make test      # Run tests
make format    # Format code (fix issues)
make lint      # Run linters
make check     # Run all checks
```

## Troubleshooting

### Test Failures

Check the job log for:
- Import errors → Missing dependencies
- Syntax errors → Code issues
- Test failures → Logic problems

Download the `coverage-py*` artifact to view the detailed HTML coverage report.

### Lint Failures

**Black failing:**
```bash
# Locally fix formatting
make format
git commit -am "style: format code with black"
git push
```

**Other linters:**
- Review the warnings/errors in the job log
- Fix issues locally
- Pylint, Flake8, and Mypy are informational and won't block merges

### UV Installation Issues

If UV install fails:
- Check network connectivity
- Verify the runner has internet access to `astral.sh`

## Advanced Configuration

### Adding a New Job

```yaml
jobs:
  my-custom-job:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install UV
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      - run: uv sync --all-extras
      - run: uv run python my_script.py
```

### Deployment

Add a deploy job that only runs on `main`:

```yaml
jobs:
  deploy:
    needs: [test, lint]
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - run: echo "Deploy to production"
```

## Best Practices

### 1. Keep Jobs Fast
- Use the UV cache action where possible
- Run lint and test jobs in parallel (they already are, as separate jobs)
- Only test what's necessary

### 2. Use Artifacts Wisely
- Store coverage reports (30 days)
- Don't store build artifacts long-term
- Clean up unnecessary artifacts

### 3. Allow Failure Strategically
- Black: fails the job (enforce formatting)
- Other linters: `|| true` (informational)
- Tests: must pass

### 4. Monitor Pipeline Performance
- Check the Actions tab for run duration trends
- Optimize slow jobs

### 5. Security
- Keep secret detection enabled
- Keep dependencies updated
- Review Dependabot / security alerts regularly

## GitHub Features

### Pull Request Integration

- Status checks required for merge (configurable in branch protection)
- Coverage shown via the Codecov PR comment/check
- Automatic re-run on demand from the Actions tab

### Badges

Add to your README.md:

```markdown
[![CI](https://github.com/valsr/haanim/actions/workflows/ci.yml/badge.svg)](https://github.com/valsr/haanim/actions/workflows/ci.yml)
```

### Scheduled Runs

Run tests nightly by adding a `schedule` trigger:

```yaml
on:
  schedule:
    - cron: "0 2 * * *"
```

## Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [UV Documentation](https://docs.astral.sh/uv/)
- [Coverage.py Documentation](https://coverage.readthedocs.io/)
- [Pytest Documentation](https://docs.pytest.org/)

## Support

For pipeline issues:
1. Check job logs in the GitHub Actions tab
2. Review this documentation
3. Run tests locally to reproduce
4. Open an issue if the problem persists
