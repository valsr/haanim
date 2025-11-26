# HAAnim

[![pipeline status](https://img.shields.io/badge/pipeline-passing-brightgreen)](https://gitlab.com/valsr/haanim/-/pipelines)
[![coverage report](https://img.shields.io/badge/coverage-check%20CI-blue)](https://gitlab.com/valsr/haanim/-/commits/main)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/valsr/haanim.svg)](https://github.com/valsr/haanim/releases)
[![License](https://img.shields.io/github/license/valsr/haanim.svg)](LICENSE)

A Home Assistant custom component for HAAnim integration.

## Description

HAAnim is a custom integration for Home Assistant that allows you to [describe what your integration does].

## Features

- Easy configuration through the UI
- [Add your features here]
- [Add more features]

## Installation

### HACS (Recommended)

#### Quick Install

1. Open **HACS** → **⋮** (three dots) → **Custom repositories**
2. Repository: `https://gitlab.com/valsr/haanim`
3. Category: **Integration**
4. Click **ADD**
5. **HACS** → **Integrations** → **+ Explore & Download**
6. Search **"HAAnim"** → **Download**
7. **Restart Home Assistant**

For detailed instructions, see [HACS_QUICKSTART.md](HACS_QUICKSTART.md) or
[HACS_INTEGRATION.md](HACS_INTEGRATION.md).

### Manual Installation

1. Copy the `custom_components/haanim` folder to your Home Assistant's `custom_components` directory
2. If the `custom_components` directory doesn't exist, create it in your Home Assistant
   configuration directory
3. Restart Home Assistant

## Configuration

1. Go to Home Assistant Settings
2. Select "Devices & Services"
3. Click "+ Add Integration"
4. Search for "HAAnim"
5. Follow the configuration steps

## Usage

After installation and configuration, you can [describe how to use your integration].

## Development

### Quick Start with Pre-configured Container (Recommended)

The fastest way to develop and test the integration is using the pre-configured container image:

```bash
# Clone the repository
git clone https://gitlab.com/valsr/haanim.git
cd haanim

# Build and start the development environment (one command!)
./podman/build-and-run.sh
```

This will:

- ✅ Build a pre-configured Home Assistant image (~5 minutes first time)
- ✅ Start the container with your code mounted for live development
- ✅ Auto-login as admin (no password needed)
- ✅ HACS pre-installed and configured
- ✅ HAAnim integration pre-configured
- ✅ Automatically open your browser to Home Assistant

**Development workflow:**

```bash
# Edit code in custom_components/haanim/
vim custom_components/haanim/sensor.py

# Restart to apply changes (no rebuild needed!)
./podman/restart.sh

# View logs
./podman/logs.sh

# Stop when done
./podman/stop.sh
```

**Pre-configured features:**

- Admin credentials: username `admin`, password `admin` (auto-login enabled)
- HACS installed and ready
- HAAnim integration already configured
- Debug logging enabled
- All setup wizards completed

See [CONTAINER_DEV.md](CONTAINER_DEV.md) or [QUICKSTART_CONTAINER.md](QUICKSTART_CONTAINER.md)
for complete documentation.

### VS Code Tasks (Recommended for VS Code Users)

The project includes pre-configured VS Code tasks for an optimal development experience:

**Quick Start:**

1. Open the project in VS Code
2. Press **`Ctrl+Shift+B`** (or **`Cmd+Shift+B`** on Mac)
3. Select "Container: Build and Run"
4. Home Assistant starts automatically and opens in your browser!

**Available Features:**

- One-click container build and start
- Automatic browser opening
- Run and Debug configurations
- Integrated testing and linting
- Container management tasks
- Python debugging support

See [VSCODE_TASKS.md](VSCODE_TASKS.md) for complete documentation.

### VS Code DevContainer

For an integrated development experience:

1. Open this project in VS Code
2. Click "Reopen in Container" when prompted (or use Command Palette: "Dev Containers: Reopen in Container")
3. VS Code will start Home Assistant and configure the development environment
4. Start coding with full IntelliSense and debugging support

**Note**: DevContainer support with Podman may require additional setup. See the VS Code documentation for Podman integration.

### Manual Setup

For local development without containers:

```bash
# Clone the repository
git clone https://gitlab.com/valsr/haanim.git
cd haanim

# Install UV (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or use the Makefile
make install

# Sync all dependencies including dev tools
uv sync --all-extras
# Or: make dev

# Run tests
uv run pytest
# Or: make test

# Format code
uv run black custom_components/haanim/
# Or: make format

# Run linting
uv run pylint custom_components/haanim/
# Or: make lint
```

#### Alternative: Traditional Setup

If you prefer not to use UV:

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install homeassistant
pip install -e ".[dev]"

# Copy custom component to your Home Assistant config
cp -r custom_components/haanim ~/.homeassistant/custom_components/

# Start Home Assistant
hass -c ~/.homeassistant
```

### Available Make Commands

```bash
make help      # Show all available commands
make install   # Install UV and sync dependencies
make sync      # Sync dependencies with lockfile
make dev       # Install dev dependencies
make test      # Run tests with pytest
make lint      # Run linting checks
make format    # Format code with black
make check     # Run all checks
```

## Continuous Integration

This project uses GitLab CI for automated testing and quality checks. Every push and merge request triggers:

- **Multi-version testing**: Tests run on Python 3.11 and 3.12
- **Code quality checks**: Black, Pylint, Flake8, and Mypy
- **Coverage reporting**: Automatic coverage calculation and reporting
- **Security scanning**: Secret detection and dependency scanning

See [GITLAB_CI_GUIDE.md](GITLAB_CI_GUIDE.md) for detailed pipeline documentation.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

If you encounter any issues or have questions:

- Open an issue on [GitLab](https://gitlab.com/valsr/haanim/-/issues)
- Check the [Home Assistant Community](https://community.home-assistant.io/)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This is a custom component and is not officially supported by Home Assistant.
