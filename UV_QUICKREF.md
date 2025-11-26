# UV Quick Reference

## Essential Commands

### Setup
```bash
make install          # Install UV and sync dependencies
make dev             # Install with dev dependencies
```

### Development
```bash
make test            # Run tests
make format          # Format code
make lint            # Run linters
make check           # Run all checks
```

### Package Management
```bash
uv add <package>              # Add production dependency
uv add --dev <package>        # Add dev dependency
uv remove <package>           # Remove dependency
uv sync                       # Sync with lockfile
uv sync --upgrade             # Update all packages
```

### Running Commands
```bash
uv run pytest                 # Run tests
uv run black .                # Format code
uv run pylint custom_components/haanim/
uv run mypy custom_components/haanim/
```

## Files

- `pyproject.toml` - Project config & dependencies
- `uv.lock` - Dependency lockfile (commit this!)
- `.python-version` - Python version (3.12)
- `uv.toml` - UV configuration
- `.venv/` - Virtual environment (auto-created)

## Workflow

1. **Clone & Setup**
   ```bash
   git clone <repo>
   cd haanim
   make install
   ```

2. **Make Changes**
   ```bash
   # Edit code...
   make format
   make test
   ```

3. **Add Dependency**
   ```bash
   uv add requests
   git add pyproject.toml uv.lock
   git commit -m "feat: add requests"
   ```

4. **Before Commit**
   ```bash
   make check    # Format + Lint
   make test     # Run tests
   ```

## Help

- Full guide: `UV_GUIDE.md`
- Migration notes: `UV_MIGRATION.md`
- Contributing: `CONTRIBUTING.md`
- Make commands: `make help`
