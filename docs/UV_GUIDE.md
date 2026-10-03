# UV Package Management Guide

This project uses [UV](https://docs.astral.sh/uv/) for fast and reliable Python package management.

## Why UV?

UV is a modern Python package manager that offers:

- **Speed**: 10-100x faster than pip
- **Reliability**: Built-in dependency resolution
- **Compatibility**: Drop-in replacement for pip and pip-tools
- **Simplicity**: Single tool for package and project management
- **Reproducibility**: Automatic lockfile generation

## Installation

### Quick Install

```bash
# macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or use the Makefile
make install
```

### Alternative Methods

```bash
# Via pip
pip install uv

# Via Homebrew (macOS)
brew install uv

# Via pipx
pipx install uv
```

## Basic Usage

### Installing Dependencies

```bash
# Install all dependencies from pyproject.toml
uv sync

# Install with dev dependencies
uv sync --all-extras

# Using Makefile shortcuts
make install  # Installs UV and syncs dependencies
make dev      # Syncs with dev dependencies
```

### Running Commands

UV automatically uses the project's virtual environment:

```bash
# Run pytest
uv run pytest

# Run black
uv run black custom_components/haanim/

# Run pylint
uv run pylint custom_components/haanim/

# Run mypy
uv run mypy custom_components/haanim/

# Or use Makefile commands
make test    # Run tests
make format  # Format code
make lint    # Run linters
make check   # Run all checks
```

### Adding Dependencies

```bash
# Add a production dependency
uv add <package-name>

# Add a development dependency
uv add --dev <package-name>

# Add a specific version
uv add "package-name>=1.0.0,<2.0.0"

# Example: Add requests
uv add requests

# Example: Add pytest-asyncio as dev dependency
uv add --dev pytest-asyncio
```

### Removing Dependencies

```bash
# Remove a dependency
uv remove <package-name>

# Remove a dev dependency
uv remove --dev <package-name>
```

### Updating Dependencies

```bash
# Update all dependencies
uv sync --upgrade

# Update a specific package
uv add --upgrade <package-name>

# Update lockfile without installing
uv lock --upgrade
```

## Project Structure

```
haanim/
├── pyproject.toml      # Project metadata and dependencies
├── uv.lock             # Lockfile (auto-generated, commit this)
├── .python-version     # Python version for the project
├── .venv/              # Virtual environment (auto-created)
└── custom_components/  # Source code
```

## pyproject.toml

Our `pyproject.toml` contains:

- **Project metadata**: name, version, description, authors
- **Dependencies**: Required packages for the integration
- **Optional dependencies**: Dev tools (black, pylint, mypy, pytest)
- **Tool configurations**: Settings for black, pylint, mypy, pytest

Example:

```toml
[project]
name = "haanim"
version = "0.1.0"
dependencies = [
    "homeassistant>=2024.1.0",
]

[project.optional-dependencies]
dev = [
    "black>=24.0.0",
    "pylint>=3.0.0",
    # ... more dev tools
]
```

## Lockfile (uv.lock)

UV automatically generates and maintains a `uv.lock` file:

- **Always commit this file** to version control
- Ensures reproducible builds across machines
- Contains exact versions of all dependencies and sub-dependencies
- Automatically updated when you add/remove packages

## Virtual Environment

UV creates a virtual environment in `.venv/`:

- **Automatically activated** when using `uv run`
- Located in the project directory
- Can be manually activated if needed:
  ```bash
  source .venv/bin/activate  # Linux/macOS
  .venv\Scripts\activate     # Windows
  ```

## Common Workflows

### Setting Up a New Development Environment

```bash
# Clone the repository
git clone https://github.com/valsr/haanim.git
cd haanim

# Install UV and dependencies
make install

# Install dev dependencies
make dev

# Run tests to verify setup
make test
```

### Daily Development

```bash
# Format code before committing
make format

# Run linting
make lint

# Run tests
make test

# Run all checks
make check
```

### Updating Dependencies

```bash
# Update all dependencies
uv sync --upgrade

# Test that everything still works
make test

# Commit the updated uv.lock
git add uv.lock
git commit -m "chore: update dependencies"
```

### Adding a New Feature Requiring a Package

```bash
# Add the package
uv add new-package

# The lockfile is automatically updated
# Test your changes
make test

# Commit both pyproject.toml and uv.lock
git add pyproject.toml uv.lock
git commit -m "feat: add new-package for feature X"
```

## Migrating from pip/requirements.txt

If you had `requirements.txt` files:

```bash
# UV can read requirements.txt files
uv pip install -r requirements.txt

# But better: add to pyproject.toml
uv add $(cat requirements.txt | grep -v '^#' | tr '\n' ' ')
```

## Troubleshooting

### UV Command Not Found

```bash
# Ensure UV is in your PATH
export PATH="$HOME/.cargo/bin:$PATH"

# Or reinstall
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Lockfile Out of Sync

```bash
# Regenerate the lockfile
uv lock

# Or force sync
uv sync --reinstall
```

### Virtual Environment Issues

```bash
# Remove and recreate the virtual environment
rm -rf .venv
uv sync
```

### Python Version Mismatch

```bash
# Check your Python version
python --version

# UV uses the version specified in .python-version
# Install the correct Python version if needed
```

## CI/CD Integration

### GitHub Actions (Current Platform)

The project includes a comprehensive `.github/workflows/ci.yml` that:
- Tests on Python 3.12 and 3.13
- Runs all linting and formatting checks
- Generates coverage reports
- Scans for committed secrets

Example step from our GitHub Actions workflow:

```yaml
steps:
  - name: Install UV
    run: curl -LsSf https://astral.sh/uv/install.sh | sh

  - name: Set up Python
    run: |
      echo "$HOME/.cargo/bin" >> $GITHUB_PATH
      uv python install 3.12

  - name: Install dependencies
    run: uv sync --all-extras

  - name: Run tests
    run: uv run pytest

  - name: Run linters
    run: |
      uv run black --check .
      uv run pylint custom_components/haanim/
      uv run mypy custom_components/haanim/
```

## Resources

- [UV Documentation](https://docs.astral.sh/uv/)
- [UV GitHub Repository](https://github.com/astral-sh/uv)
- [Python Packaging Guide](https://packaging.python.org/)

## Comparison with Other Tools

| Feature        | UV  | pip    | Poetry | PDM    |
| -------------- | --- | ------ | ------ | ------ |
| Speed          | ⚡️⚡️⚡️ | 🐌      | ⚡️      | ⚡️      |
| Lockfile       | ✅   | ❌      | ✅      | ✅      |
| Resolver       | ✅   | ⚠️      | ✅      | ✅      |
| `uv run`       | ✅   | ❌      | ✅      | ✅      |
| pyproject.toml | ✅   | ⚠️      | ✅      | ✅      |
| Maturity       | New | Stable | Mature | Mature |

## FAQ

**Q: Should I commit uv.lock?**
A: Yes! Always commit the lockfile to ensure reproducible builds.

**Q: Can I still use pip?**
A: Yes, but UV is recommended for consistency. UV can read pip requirements.

**Q: What if someone doesn't have UV installed?**
A: They can run `make install` or follow traditional pip setup in the README.

**Q: Does UV work with Home Assistant?**
A: Yes! UV manages development dependencies. Home Assistant users don't need UV.

**Q: How do I update just one package?**
A: Run `uv add --upgrade package-name`
