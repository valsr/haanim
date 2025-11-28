# Contributing to HAAnim

Thank you for your interest in contributing to HAAnim! This document provides guidelines and
instructions for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://gitlab.com/YOUR_USERNAME/haanim.git`
3. Create a new branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test your changes
6. Commit your changes: `git commit -m "Add your feature"`
7. Push to your fork: `git push origin feature/your-feature-name`
8. Create a merge request

## Development Setup

### Quick Start with Pre-configured Container (Recommended)

The fastest way to develop and test:

```bash
# Clone the repository
git clone https://gitlab.com/valsr/haanim.git
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
git clone https://gitlab.com/valsr/haanim.git
cd haanim

# Install UV and dependencies
make install

# Install dev dependencies
make dev

# Run tests
make test

# Format code
make format

# Run linting
make lint
```

See [docs/UV_GUIDE.md](docs/UV_GUIDE.md) for comprehensive UV usage instructions.

#### Traditional pip Setup

If you prefer not to use UV:

```bash
# Clone the repository
git clone https://gitlab.com/valsr/haanim.git
cd haanim

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Home Assistant for development
pip install homeassistant

# Install development dependencies
pip install black flake8 pylint mypy pytest
```

## Code Style

- Follow PEP 8 guidelines
- Use meaningful variable and function names
- Add docstrings to all functions and classes (Google style)
- Keep lines under 110 characters
- Use type hints where appropriate

## Testing

Before submitting a merge request:

1. Run the test suite: `make test` (or `uv run pytest`)
2. Ensure code is formatted: `make format` (or `uv run black custom_components/haanim/`)
3. Run linting checks: `make lint` (or use individual linters)
4. Test your changes in a Home Assistant development environment
5. Ensure all existing functionality still works
6. Add tests for new features if applicable

### Running Tests

```bash
# Using Make
make test

# Using UV directly
uv run pytest

# Run with coverage
uv run pytest --cov=custom_components/haanim

# Run specific test file
uv run pytest tests/test_config_flow.py

# Run with verbose output
uv run pytest -v
```

## Commit Messages

- Use clear and descriptive commit messages
- Start with a verb in present tense (e.g., "Add", "Fix", "Update")
- Reference issues when applicable (e.g., "Fix #123")

## Merge Request Process

1. Update the CHANGELOG.md with details of your changes
2. Update the README.md if you've added new features or changed functionality
3. Ensure your code follows the style guidelines
4. Your merge request will be reviewed by maintainers

## Questions?

If you have questions, feel free to:

- Open an issue on GitLab
- Ask in the Home Assistant community forums

## Code of Conduct

Be respectful and constructive in all interactions.
