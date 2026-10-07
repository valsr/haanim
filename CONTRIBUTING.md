# Contributing to HAAnim

Thank you for your interest in contributing to HAAnim! This document provides guidelines and
instructions for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/haanim.git`
3. Create a new branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test your changes
6. Commit your changes: `git commit -m "Add your feature"`
7. Push to your fork: `git push origin feature/your-feature-name`
8. Create a pull request

## Development Setup

### Quick Start with Pre-configured Container (Recommended)

The fastest way to develop and test:

```bash
# Clone the repository
git clone https://github.com/valsr/haanim.git
cd haanim

# Build and start the development environment (one command!)
./podman/build-and-run.sh
```

This will:

- Build a pre-configured Home Assistant image
- Start the container with your code live-mounted
- Auto-login as admin (no password needed)
- HACS pre-installed and configured
- HAAnim integration pre-configured
- Automatically open your browser

After making changes to the code:

```bash
# Restart to apply changes
./podman/restart.sh

# View logs to debug
./podman/logs.sh

# Stop when done
./podman/stop.sh
```

See [docs/CONTAINER_DEV.md](docs/CONTAINER_DEV.md) or [podman/README.md](podman/README.md) for complete
documentation.

### Using VS Code (Recommended)

1. Open the project in VS Code
2. Press **Ctrl+Shift+B** (or Cmd+Shift+B on Mac)
3. Select "Container: Build and Run"
4. VS Code will build, start, and open your browser automatically

All container tasks are available via:

- **Ctrl+Shift+B** - Quick access to build task
- **Ctrl+Shift+P** → "Tasks: Run Task" - All available tasks

### Manual Setup with UV

For local development without containers:

UV is a fast Python package manager that makes dependency management easy:

```bash
# Clone the repository
git clone https://github.com/valsr/haanim.git
cd haanim

# Install UV (https://docs.astral.sh/uv/), then the project with its development dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Format code
uv run black .

# Run linting and type checks
uv run pylint custom_components src
uv run mypy custom_components src
```

See [docs/UV_GUIDE.md](docs/UV_GUIDE.md) for comprehensive UV usage instructions.

#### Traditional pip Setup

If you prefer not to use UV:

```bash
# Clone the repository
git clone https://github.com/valsr/haanim.git
cd haanim

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the package with its development dependencies, Home Assistant among them
pip install -e ".[dev]"
```

## Code Style

- Follow PEP 8 guidelines
- Use meaningful variable and function names
- Add docstrings to all functions and classes (Google style)
- Keep lines under 110 characters
- Use type hints where appropriate

## Testing

Before submitting a pull request, all of this has to pass; CI runs the same:

```bash
uv run pytest                                        # every test, and the overall coverage gate
uv run python scripts/check-public-api-coverage.py   # haa, decorators, events and errors at 100%
uv run black --check .
uv run pylint custom_components src                  # no messages
uv run mypy custom_components src                    # no errors
uv run pyright src custom_components examples        # no errors
```

- Every rule a change implements has a test. Tests do not sleep or read the real clock: use the fake clock
  (`await clock.advance(...)`) or, for a whole automation, `haanim.testing.AutomationHarness`.
- `tests/engine` must not need Home Assistant; `tests/integration` uses
  `pytest-homeassistant-custom-component`.
- The frontend tests are in `tests/frontend` and run with node 22 or later (`scripts/test-frontend.sh`);
  `uv run pytest` runs them too if node is installed.
- For a change that touches the integration or the frontend, also run the end-to-end check against the
  development container: `./build-and-run.sh`, then `uv run python scripts/e2e-smoke.py`.

### Running Tests

```bash
# Everything
uv run pytest

# One file, without the coverage gate
uv run pytest tests/engine/test_card.py --no-cov

# The examples' own tests
uv run pytest examples/tests --no-cov
```

## Commit Messages

- Use clear and descriptive commit messages
- Start with a verb in present tense (e.g., "Add", "Fix", "Update")
- Reference issues when applicable (e.g., "Fix #123")

## Pull Request Process

1. Update the CHANGELOG.md with details of your changes
2. Update the README.md if you've added new features or changed functionality
3. Ensure your code follows the style guidelines
4. Your pull request will be reviewed by maintainers

## Releasing

One version number serves the integration and the package. A release is made from `main`:

1. Set the version in `src/haanim/__init__.py` and in `custom_components/haanim/manifest.json` (a test
   fails when they differ), and move the entries under "Unreleased" in `CHANGELOG.md` to the new version.
2. Publish a GitHub release whose tag is the version, with or without a leading `v` (`v0.3.0`).

Publishing the release runs `.github/workflows/release.yml`, which

- builds `haanim.zip`, the integration with the engine in it, and attaches it to the release: this is what
  HACS installs;
- builds the `haanim` package and publishes it on [PyPI](https://pypi.org/project/haanim/). PyPI trusts the
  workflow itself (a trusted publisher for the repository `valsr/haanim`, the workflow `release.yml` and
  the environment `pypi`), so there is no token to keep.

Read the Docs builds the documentation from `main` (`latest`) and from every release tag (`stable`), as
`.readthedocs.yaml` says. `.github/workflows/validate.yml` runs hassfest and the HACS validation on every
pull request.

## Questions?

If you have questions, feel free to:

- Open an issue on GitHub
- Ask in the Home Assistant community forums

## Code of Conduct

Be respectful and constructive in all interactions.
