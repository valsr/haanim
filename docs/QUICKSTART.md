# HAAnim Development - Quick Start Guide

## Prerequisites

- Podman or Docker installed
- Git installed
- (Optional) VS Code for integrated development

## Getting Started - One Command

### 1. Clone the Repository

```bash
git clone https://gitlab.com/valsr/haanim.git
cd haanim
```

### 2. Build and Start Development Environment

```bash
./podman/build-and-run.sh
```

That's it! This single command will:

- ✅ Build a pre-configured Home Assistant image (~5 minutes first time)
- ✅ Start the container with your code mounted
- ✅ Automatically open your browser to Home Assistant
- ✅ Log you in as admin (no password needed!)

**Everything is pre-configured:**

- Admin user already created (username: `admin`, password: `admin`)
- HACS installed and ready to use
- HAAnim integration pre-configured
- Debug logging enabled
- No setup wizard to complete!

### 3. That's It - Start Coding

Your code in `custom_components/haanim/` is live-mounted. Just edit and restart!

## Development Workflow

### Making Changes

1. Edit code in `custom_components/haanim/`
2. Restart to apply: `./podman/restart.sh`
3. Check logs: `./podman/logs.sh`
4. Test in browser: <http://localhost:8123>

### Common Commands

| Command                    | Description                           |
| -------------------------- | ------------------------------------- |
| `./podman/build-and-run.sh`   | Build image and start (one command!)  |
| `./podman/restart.sh`         | Restart after code changes            |
| `./podman/stop.sh`            | Stop container                        |
| `./podman/logs.sh`            | View real-time logs (Ctrl+C to exit)  |
| `./podman/shell.sh`           | Open shell in container               |
| `./podman/build-image.sh`     | Rebuild image (after config changes)  |

### VS Code Integration (Recommended)

For the best development experience:

1. Open the project in VS Code
2. Press **Ctrl+Shift+B** (or Cmd+Shift+B on Mac)
3. Select "Container: Build and Run"
4. Done! VS Code will build, start, and open your browser automatically

**Or use the Command Palette:**

- `Ctrl+Shift+P` → "Tasks: Run Task" → Select any container task

## Pre-configured Features

Your development container includes:

- 🔐 **Auto-login** - No password needed (trusted networks enabled)
- 👤 **Admin user** - username: `admin`, password: `admin`
- 📦 **HACS installed** - Ready to use in the sidebar
- 🔧 **HAAnim integrated** - Already added to Devices & Services
- 🐛 **Debug logging** - HAAnim logs at debug level
- 🔄 **Live code mounting** - Changes apply on restart

## Project Structure

```text
haanim/
├── custom_components/haanim/   # Your integration code (live-mounted!)
│   ├── __init__.py             # Main entry point
│   ├── config_flow.py          # UI configuration
│   ├── const.py                # Constants
│   ├── manifest.json           # Integration metadata
│   └── translations/           # UI translations
├── podman/                     # Podman/Docker development environment
│   ├── container-config/       # Pre-baked container configuration
│   ├── build-and-run.sh        # One-command setup
│   ├── build-image.sh          # Build image only
│   └── ...                     # Container management scripts
├── docs/                       # Additional documentation
│   ├── CONTAINER_DEV.md        # Complete container documentation
│   ├── VSCODE_TASKS.md         # VS Code tasks guide
│   └── ...                     # More guides
├── Dockerfile.dev              # Development image definition
└── docker-compose.dev.yml      # Compose file for built image
```

## Debugging

### View Logs

```bash
./podman/logs.sh
```

Look for lines with `custom_components.haanim` - these are your integration's logs.

### Check Integration Status

1. Go to **Settings** → **Devices & Services**
2. Find "HAAnim" in the list (should already be there!)
3. Click to view entities and configuration

### Common Issues

**Container won't start:**

```bash
podman rm -f haanim-dev
./podman/build-and-run.sh
```

**Changes not applying:**

```bash
./podman/restart.sh    # Restart container to apply code changes
```

**Need to rebuild (after config changes):**

```bash
./podman/build-image.sh  # Rebuild image
./podman/build-and-run.sh  # Or rebuild and start
```

**Port 8123 already in use:**

```bash
podman ps -a | grep 8123  # Find conflicting container
podman stop <container-name>
```

## Modifying Container Configuration

To change pre-configured settings (admin password, integrations, etc.):

1. Edit files in `podman/container-config/`
2. Rebuild the image: `./podman/build-image.sh`
3. Start fresh: `./podman/build-and-run.sh`

See [podman/container-config/README.md](podman/container-config/README.md) for details.

## Next Steps

- **Complete Guide**: [docs/CONTAINER_DEV.md](docs/CONTAINER_DEV.md) - Full container documentation
- **Quick Reference**: [docs/QUICKSTART_CONTAINER.md](docs/QUICKSTART_CONTAINER.md) - Command cheat sheet
- **Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md) - Development guidelines
- **VS Code Tasks**: [docs/VSCODE_TASKS.md](docs/VSCODE_TASKS.md) - Task automation
- **Code Standards**: [.github/copilot-instructions.md](.github/copilot-instructions.md)

## Tips

- 🚀 First build takes ~5 minutes, subsequent builds use cache and are faster
- 💻 Code changes only need restart, not rebuild
- 🔧 Configuration changes need image rebuild
- 🧪 Use `make test` for unit tests
- 🎨 Use `make format` to auto-format code before committing
- 📝 Use `make lint` to check code quality

Happy coding! 🚀
