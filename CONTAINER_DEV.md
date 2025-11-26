# HAAnim Development Container

A fully pre-configured Home Assistant development container with HACS and HAAnim integration built-in.

## Features

✅ **Pre-configured** - Everything setup out of the box
✅ **No manual steps** - Admin user, HACS, and HAAnim ready
✅ **Auto-login** - Trusted networks enabled for localhost
✅ **Live reload** - Code changes reflect after restart
✅ **Single command** - Build and run with one script

## Quick Start

### Build and Run (Recommended)

```bash
./podman/build-and-run.sh
```

This will:
1. Stop any existing container
2. Build the development image
3. Start the container
4. Wait for Home Assistant to initialize
5. Open your browser automatically

### Manual Build

```bash
# Build the image
./podman/build-image.sh

# Run the container
podman run -d \
  --name haanim-dev \
  -p 8123:8123 \
  --network host \
  -v ./custom_components/haanim:/config/custom_components/haanim:z \
  haanim-dev:latest
```

## What's Pre-configured

### User Credentials
- **Username**: `admin`
- **Password**: `admin`
- **Auto-login**: Enabled for localhost (no password needed)

### Components

- ✅ **Onboarding**: Completed
- ✅ **HACS**: Installed and enabled as integration (ready to use)
- ✅ **HAAnim**: Pre-configured and ready
- ✅ **Trusted Networks**: All local networks trusted

**HACS Setup:**

- HACS is installed as a custom component
- Added as an integration (visible in Devices & Services)
- Onboarding completed automatically
- Appears in sidebar for easy access
- Ready to browse and install integrations/themes
- GitHub token can be added later for downloading repositories

### Development Setup

- HAAnim code mounted from `./custom_components/haanim/`
- Changes reflect immediately after container restart
- Debug logging enabled for HAAnim

## Container Management

### Using Scripts

```bash
# Build and run (one command)
./podman/build-and-run.sh

# Rebuild image only
./podman/build-image.sh

# Using existing scripts (with current container)
./podman/restart.sh    # Restart Home Assistant
./podman/logs.sh       # View logs
./podman/stop.sh       # Stop container
./podman/shell.sh      # Open shell in container
```

### Manual Commands

```bash
# Start
podman start haanim-dev

# Stop
podman stop haanim-dev

# Restart
podman restart haanim-dev

# Logs
podman logs -f haanim-dev

# Shell
podman exec -it haanim-dev /bin/bash

# Remove
podman stop haanim-dev && podman rm haanim-dev
```

## Development Workflow

1. **Make code changes** in `custom_components/haanim/`
2. **Restart container**: `podman restart haanim-dev`
3. **Test** in Home Assistant
4. **View logs**: `podman logs -f haanim-dev`
5. Repeat!

## Configuration Files

### Image Build Configuration

```text
podman/container-config/
├── .storage/
│   ├── onboarding                      # Onboarding completed
│   ├── auth                            # User: admin
│   ├── auth_provider.homeassistant     # Password: admin
│   └── core.config_entries             # HACS & HAAnim pre-configured
├── configuration.yaml                   # Home Assistant config
├── automations.yaml                     # Empty
├── scenes.yaml                          # Empty
└── scripts.yaml                         # Empty
```

**Note:** HACS storage files (`hacs.hacs`, `hacs.repositories`, etc.) are created automatically
by HACS on first run. Only the config entry is pre-configured.

### Dockerfile

- **Base**: `homeassistant/home-assistant:latest`
- **Components**: HACS + HAAnim
- **Config**: Pre-configured storage files
- **Network**: Trusted networks enabled

## Rebuilding the Image

Rebuild when:
- Home Assistant base image is updated
- HACS version needs updating
- Configuration files change

```bash
./podman/build-and-run.sh
```

Or rebuild without running:

```bash
podman build -t haanim-dev:latest -f Dockerfile.dev .
```

## Accessing Home Assistant

- **URL**: http://localhost:8123
- **Username**: `admin`
- **Password**: `admin`
- **Or**: Just open URL (auto-login from localhost)

## Troubleshooting

### Container won't start

```bash
# Check logs
podman logs haanim-dev

# Remove and rebuild
podman stop haanim-dev && podman rm haanim-dev
./podman/build-and-run.sh
```

### HACS not appearing in sidebar

HACS should appear automatically in the sidebar after first start.

**If HACS is missing:**

1. Check Devices & Services for HACS integration
2. Check logs: `podman logs haanim-dev | grep -i hacs`
3. Verify HACS is installed: `podman exec haanim-dev ls /config/custom_components/hacs`
4. Rebuild if needed: `./podman/build-and-run.sh`

**Adding repositories:**

- HACS is fully functional and ready to use
- GitHub authentication may be required for downloading some repositories
- Browse and install integrations/themes from the HACS UI

### Changes not reflecting

```bash
# Restart the container
podman restart haanim-dev

# Or rebuild if configuration changed
./podman/build-and-run.sh
```

### Port already in use

```bash
# Stop existing container
podman stop haanim-dev

# Or change port in docker-compose.dev.yml
# ports:
#   - '8124:8123'  # Use different host port
```

## Image Management

### List images

```bash
podman images | grep haanim-dev
```

### Remove old images

```bash
podman rmi haanim-dev:latest
```

### Export image

```bash
# Export
podman save haanim-dev:latest -o haanim-dev.tar

# Import
podman load -i haanim-dev.tar
```

## Comparison with Runtime Setup

| Feature        | Pre-built Image        | Runtime Setup            |
| -------------- | ---------------------- | ------------------------ |
| Startup time   | Fast                   | Slow (installs on start) |
| Onboarding     | ✅ Done                 | ⚠️ Manual                 |
| HACS Setup     | ✅ Enabled & Configured | ⚠️ Manual install/setup   |
| HACS Sidebar   | ✅ Visible              | ⚠️ After manual setup     |
| HAAnim Config  | ✅ Pre-configured       | ⚠️ Manual add             |
| Rebuild needed | Only for updates       | Never                    |
| Image size     | ~1.5GB                 | ~1.2GB                   |

## VS Code Integration

Update `.vscode/tasks.json` to use the new container:

```json
{
  "label": "Build and Run Dev Container",
  "type": "shell",
  "command": "./podman/build-and-run.sh",
  "group": {
    "kind": "build",
    "isDefault": true
  }
}
```

Press **Ctrl+Shift+B** to build and run!

## Next Steps

1. Run `./podman/build-and-run.sh`
2. Wait for browser to open
3. You're ready to develop!

Everything is pre-configured - no manual setup required! 🎉
