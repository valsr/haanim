# GitLab CI Configuration Guide

This document explains the GitLab CI/CD pipeline configuration for the HAAnim project.

## Overview

The GitLab CI pipeline is configured in `.gitlab-ci.yml` and uses UV for fast, reliable Python package management. The pipeline runs automatically on every push and merge request.

## Pipeline Structure

### Stages

1. **Setup** - Environment preparation (implicit in each job)
2. **Test** - Run pytest on multiple Python versions
3. **Lint** - Code quality checks
4. **Security** - Security scanning

### Jobs

#### Test Jobs

**`test:python3.11`** and **`test:python3.12`**
- Runs on Python 3.11 and 3.12 respectively
- Executes pytest with coverage reporting
- Generates coverage artifacts in multiple formats
- Coverage badge automatically extracted from output

```yaml
test:python3.12:
  stage: test
  image: python:3.12
  script:
    - uv run pytest --cov=custom_components/haanim --cov-report=xml
  coverage: '/(?i)total.*? (100(?:\.0+)?\%|[1-9]?\d(?:\.\d+)?\%)$/'
```

**Artifacts Generated:**
- `coverage.xml` - Cobertura format for GitLab integration
- `htmlcov/` - HTML coverage report
- Available for 30 days

#### Lint Jobs

**`lint:black`** - Code Formatting Check
- Verifies code follows Black formatting rules
- Line length: 110 characters
- **Fails the pipeline** if code is not formatted (allow_failure: false)

**`lint:pylint`** - Static Code Analysis
- Comprehensive Python linting
- Allows failure (informational)

**`lint:flake8`** - Style Guide Enforcement
- PEP 8 compliance checking
- Allows failure (informational)

**`lint:mypy`** - Type Checking
- Static type checking
- Allows failure (informational)

**`lint:all`** - Combined Check (Manual)
- Runs all linting tools in sequence
- Manual trigger only
- Provides comprehensive quality report

#### Security Jobs

**`secret_detection`**
- Scans for accidentally committed secrets
- Uses GitLab's built-in security template
- Runs on every pipeline

## Configuration Details

### Variables

```yaml
variables:
  UV_VERSION: "0.9.12"          # UV version to install
  PYTHON_VERSION: "3.12"         # Default Python version
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  UV_CACHE_DIR: "$CI_PROJECT_DIR/.cache/uv"
  SECRET_DETECTION_ENABLED: "true"
```

### Caching

The pipeline caches:
- UV downloads and builds
- pip cache
- Virtual environment (`.venv/`)

**Cache Key:** `${CI_COMMIT_REF_SLUG}-${PYTHON_VERSION}`
- Different branches get separate caches
- Different Python versions get separate caches

**Benefits:**
- First run: ~2-3 minutes
- Cached runs: ~30-60 seconds
- Significant speedup for development

### Base Template

All jobs extend `.uv_setup`:

```yaml
.uv_setup:
  image: python:${PYTHON_VERSION}
  before_script:
    - curl -LsSf https://astral.sh/uv/install.sh | sh
    - export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    - uv sync --all-extras
```

This ensures:
- UV is installed
- Dependencies are synced
- Environment is consistent across all jobs

## Coverage Reporting

### GitLab Integration

Coverage is automatically extracted and displayed:
- On merge request diff
- In pipeline view
- As a project badge

**Coverage Regex:**
```yaml
coverage: '/(?i)total.*? (100(?:\.0+)?\%|[1-9]?\d(?:\.\d+)?\%)$/'
```

Extracts percentage from pytest output:
```
TOTAL    100    50     50%
```

### Coverage Artifacts

Three formats are generated:

1. **Terminal Output** - Immediate feedback in job logs
2. **XML (Cobertura)** - For GitLab coverage visualization
3. **HTML** - Detailed browseable report

Download HTML coverage from job artifacts to view locally.

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

## Pipeline Optimization

### Speed Improvements

1. **Parallel Execution**: Test and lint jobs run in parallel
2. **Caching**: Dependencies cached between runs
3. **UV Speed**: 10-100x faster than pip
4. **Targeted Linting**: Only checks custom_components/

### Resource Usage

- **Memory**: ~1GB per job
- **CPU**: 1-2 cores per job
- **Time**: 30-180 seconds per job (with cache)

### Cache Strategy

```yaml
cache:
  key: "${CI_COMMIT_REF_SLUG}-${PYTHON_VERSION}"
  paths:
    - .cache/pip
    - .cache/uv
    - .venv/
```

**Cache Behavior:**
- Branch-specific caches
- Shared across commits in same branch
- Automatically cleaned after 7 days of no use

## Troubleshooting

### Cache Issues

If you see stale dependencies:

1. **Clear project cache** in GitLab CI/CD settings
2. **Force dependency update**:
   ```yaml
   # Temporarily add to before_script
   - uv sync --reinstall
   ```

### Test Failures

Check the job log for:
- Import errors → Missing dependencies
- Syntax errors → Code issues
- Test failures → Logic problems

Download artifacts to view detailed coverage report.

### Lint Failures

**Black failing:**
```bash
# Locally fix formatting
make format
git commit -am "style: format code with black"
git push
```

**Other linters:**
- Review the warnings/errors in job log
- Fix issues locally
- Most linters allow failure, so they won't block MRs

### UV Installation Issues

If UV install fails:
- Check network connectivity
- Verify UV version is available
- Check GitLab runner compatibility

## Advanced Configuration

### Adding a New Job

```yaml
my_custom_job:
  extends: .uv_setup
  stage: test
  script:
    - uv run python my_script.py
  artifacts:
    paths:
      - output/
```

### Multi-Stage Deployment

Add deployment stages:

```yaml
stages:
  - setup
  - test
  - lint
  - security
  - deploy

deploy:production:
  stage: deploy
  script:
    - echo "Deploy to production"
  only:
    - main
```

### Custom Python Version

```yaml
test:python3.13:
  extends: .uv_setup
  image: python:3.13-rc
  stage: test
  allow_failure: true  # Allow failures for unreleased Python
```

### Matrix Testing

Test multiple configurations:

```yaml
.test_template:
  extends: .uv_setup
  stage: test
  script:
    - uv run pytest

test:python3.11:
  extends: .test_template
  image: python:3.11

test:python3.12:
  extends: .test_template
  image: python:3.12
```

## Best Practices

### 1. Keep Jobs Fast
- Use caching effectively
- Run linters in parallel
- Only test what's necessary

### 2. Use Artifacts Wisely
- Store coverage reports (30 days)
- Don't store build artifacts long-term
- Clean up unnecessary artifacts

### 3. Allow Failure Strategically
- Black: `allow_failure: false` (enforce formatting)
- Other linters: `allow_failure: true` (informational)
- Tests: `allow_failure: false` (must pass)

### 4. Monitor Pipeline Performance
- Check pipeline duration trends
- Optimize slow jobs
- Review cache hit rates

### 5. Security
- Enable secret detection
- Keep dependencies updated
- Review security reports regularly

## GitLab Features

### Merge Request Integration

- Coverage diff shown on MR
- Pipeline status required for merge
- Automatic retry on transient failures

### Badges

Add to your README.md:

```markdown
[![pipeline status](https://gitlab.com/valsr/haanim/badges/main/pipeline.svg)](https://gitlab.com/valsr/haanim/-/commits/main)
[![coverage report](https://gitlab.com/valsr/haanim/badges/main/coverage.svg)](https://gitlab.com/valsr/haanim/-/commits/main)
```

### Scheduled Pipelines

Run tests nightly:

1. Go to CI/CD → Schedules
2. Create schedule: "0 2 * * *" (2 AM daily)
3. Target branch: main
4. Variables: `SCHEDULE_TYPE=nightly`

## Resources

- [GitLab CI/CD Documentation](https://docs.gitlab.com/ee/ci/)
- [UV Documentation](https://docs.astral.sh/uv/)
- [Coverage.py Documentation](https://coverage.readthedocs.io/)
- [Pytest Documentation](https://docs.pytest.org/)

## Support

For pipeline issues:
1. Check job logs in GitLab
2. Review this documentation
3. Run tests locally to reproduce
4. Open an issue if problem persists
