# GitLab CI Quick Reference

## Pipeline Structure

```
Stages: setup → test → lint → security

Jobs:
  test:python3.13     ├─ Parallel
  lint:black         ─┤
  lint:pylint         │
  lint:flake8         │
  lint:mypy          ─┘
  secret_detection
```

## Job Status

- 🟢 **Green** = Passed
- 🔴 **Red** = Failed
- 🟡 **Yellow** = Running
- ⚪ **Gray** = Skipped/Manual

## Key Jobs

| Job                | Purpose              | Blocks MR? |
| ------------------ | -------------------- | ---------- |
| `test:python3.13`  | Tests on Python 3.13 | ✅ Yes      |
| `lint:black`       | Code formatting      | ✅ Yes      |
| `lint:pylint`      | Python linting       | ❌ No       |
| `lint:flake8`      | Style checking       | ❌ No       |
| `lint:mypy`        | Type checking        | ❌ No       |
| `secret_detection` | Security scan        | ❌ No       |

## Viewing Results

### Pipeline
1. Go to **CI/CD** → **Pipelines**
2. Click pipeline number
3. View all job statuses

### Coverage
- Shown on merge request diff
- Click job → **Artifacts** → `htmlcov/`
- Or check job output for coverage %

### Logs
- Click job name
- View real-time or complete log
- Download log if needed

## Local Testing

```bash
# Reproduce CI locally
make test              # Run tests with coverage
make format            # Fix formatting issues
make lint              # Run all linters
make check             # Run all checks

# Specific commands
uv run pytest --cov=custom_components/haanim
uv run black --check custom_components/haanim/
uv run pylint custom_components/haanim/
```

## Common Tasks

### Fix Formatting Failure
```bash
make format
git add -A
git commit -m "style: format code"
git push
```

### Fix Test Failure
```bash
# Run tests locally
make test

# Fix the failing test
# Commit and push
```

### Retry Failed Job
1. Go to pipeline
2. Click failed job
3. Click **Retry** button

### Clear Cache
1. Go to **Settings** → **CI/CD**
2. Expand **Clear runner caches**
3. Click **Clear runner caches** button

## Artifacts

### Coverage Reports
- **Location**: Test jobs → Artifacts
- **Files**: `coverage.xml`, `htmlcov/`
- **Retention**: 30 days

### Download
1. Go to job
2. Click **Browse** or **Download**
3. Select files to download

## Triggers

Pipeline runs on:
- ✅ Every push
- ✅ Every merge request
- ✅ Manual trigger
- ✅ Scheduled (if configured)

## Performance

| Run Type   | Duration      |
| ---------- | ------------- |
| First run  | 2-3 minutes   |
| Cached run | 30-60 seconds |
| Lint only  | 15-30 seconds |

## Cache

**Key**: `branch-python_version`

**Cached**:
- UV downloads
- pip cache
- `.venv/` directory

**Reset**: Automatic after 7 days unused

## Badges

Add to README:
```markdown
[![pipeline](https://gitlab.com/valsr/haanim/badges/main/pipeline.svg)](https://gitlab.com/valsr/haanim/-/commits/main)
[![coverage](https://gitlab.com/valsr/haanim/badges/main/coverage.svg)](https://gitlab.com/valsr/haanim/-/commits/main)
```

## Troubleshooting

| Issue          | Solution                         |
| -------------- | -------------------------------- |
| Pipeline stuck | Click **Cancel** and retry       |
| Cache stale    | Clear runner caches in settings  |
| Test failure   | Run `make test` locally to debug |
| Black failure  | Run `make format` to fix         |
| Slow pipeline  | Check cache hit in logs          |

## Resources

- [GITLAB_CI_GUIDE.md](GITLAB_CI_GUIDE.md) - Full documentation
- [.gitlab-ci.yml](.gitlab-ci.yml) - Pipeline config
- [GitLab CI Docs](https://docs.gitlab.com/ee/ci/)

## Quick Commands

```bash
# Check CI config locally
python3 -c "import yaml; yaml.safe_load(open('.gitlab-ci.yml'))"

# Run what CI runs
make test && make check

# Format before pushing
make format

# View recent pipelines
# → GitLab UI: CI/CD → Pipelines
```
