# GitHub Actions CI Quick Reference

## Pipeline Structure

```
Jobs (run in parallel):
  test               ├─ matrix: python 3.12, 3.13
  lint                │
  secret-detection   ─┘
```

## Job Status

- 🟢 **Green check** = Passed
- 🔴 **Red X** = Failed
- 🟡 **Yellow dot** = Running
- ⚪ **Gray** = Skipped

## Key Jobs

| Job                | Purpose              | Blocks merge?          |
| ------------------ | --------------------- | ----------------------- |
| `test`             | Tests on Python 3.12/3.13 | ✅ Yes              |
| `lint` (Black)     | Code formatting        | ✅ Yes                  |
| `lint` (Pylint)    | Python linting         | ❌ No (`\|\| true`)     |
| `lint` (Flake8)    | Style checking         | ❌ No (`\|\| true`)     |
| `lint` (Mypy)      | Type checking          | ❌ No (`\|\| true`)     |
| `secret-detection` | Security scan (Gitleaks) | ❌ No                |

## Viewing Results

### Pipeline
1. Go to the **Actions** tab
2. Click the workflow run
3. View all job statuses

### Coverage
- Shown via the Codecov check on the pull request
- Or download the `coverage-py*` artifact → `htmlcov/`

### Logs
- Click a job name
- View real-time or complete log
- Download log via the gear icon if needed

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

### Re-run a Failed Workflow
1. Go to the **Actions** tab
2. Open the failed run
3. Click **Re-run jobs**

## Artifacts

### Coverage Reports
- **Location**: `test` job → Artifacts (`coverage-py<version>`)
- **Files**: `coverage.xml`, `htmlcov/`
- **Retention**: 30 days

### Download
1. Go to the workflow run
2. Scroll to **Artifacts**
3. Click to download

## Triggers

Pipeline runs on:
- ✅ Every push to `main`, `master`, `develop`
- ✅ Every pull request targeting those branches
- ✅ Manual re-run of a previous run

## Badges

Add to README:
```markdown
[![CI](https://github.com/valsr/haanim/actions/workflows/ci.yml/badge.svg)](https://github.com/valsr/haanim/actions/workflows/ci.yml)
```

## Troubleshooting

| Issue          | Solution                              |
| -------------- | -------------------------------------- |
| Run stuck      | Cancel the run from the Actions tab and re-run |
| Test failure   | Run `make test` locally to debug       |
| Black failure  | Run `make format` to fix               |
| Slow pipeline  | Check the UV install/sync step timing  |

## Resources

- [GITHUB_CI_GUIDE.md](GITHUB_CI_GUIDE.md) - Full documentation
- [ci.yml](../.github/workflows/ci.yml) - Pipeline config
- [GitHub Actions Docs](https://docs.github.com/en/actions)

## Quick Commands

```bash
# Run what CI runs
make test && make check

# Format before pushing
make format

# View recent runs
# → GitHub UI: Actions tab
```
