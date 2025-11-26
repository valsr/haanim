# Development Environment

This directory contains scripts and configuration for the HAAnim development container.

## Quick Start

**One command to build and run everything:**

```bash
./podman/build-and-run.sh
```

This will:

- Build the pre-configured development image
- Start the container with your code mounted
- Open your browser to Home Assistant
- Auto-login as admin (no password needed)

See [CONTAINER_DEV.md](../CONTAINER_DEV.md) for complete documentation.

## Directory Structure

### Scripts

- **`build-and-run.sh`** - Build image and start container (recommended)
- **`build-image.sh`** - Build the development image only
- **`restart.sh`** - Restart the running container
- **`stop.sh`** - Stop the container
- **`logs.sh`** - View container logs
- **`shell.sh`** - Open shell inside container

### Configuration

- **`container-config/`** - Pre-configured Home Assistant files baked into the image
  - `.storage/` - Storage files (onboarding, auth, config entries, HACS)
  - `configuration.yaml` - Main HA configuration with trusted networks
  - `automations.yaml`, `scenes.yaml`, `scripts.yaml` - Empty config files
  - See [container-config/README.md](container-config/README.md) for details

### Documentation

- **[HACS_SETUP.md](HACS_SETUP.md)** - HACS setup and GitHub authentication
- **[COMPONENTS.md](COMPONENTS.md)** - Component management information
- **[PODMAN_INFO.md](PODMAN_INFO.md)** - Podman-specific troubleshooting

## Available Scripts

### Build and Run (Recommended)

Build the image and start the container in one command:

```bash
./podman/build-and-run.sh
```

### Build Image Only

Just build the image without starting it:

```bash
./podman/build-image.sh
```

### Container Management

```bash
# Restart container (apply code changes)
./podman/restart.sh

# Stop container
./podman/stop.sh

# View logs
./podman/logs.sh

# Open shell
./podman/shell.sh
```

## Development Workflow

1. **Start**: Run `./podman/build-and-run.sh` (first time builds image ~5 minutes)
2. **Code**: Edit files in `custom_components/haanim/`
3. **Apply**: Run `./podman/restart.sh` to restart container
4. **Test**: Check <http://localhost:8123>
5. **Debug**: Run `./podman/logs.sh` to view logs

Your code is live-mounted, so changes apply immediately on restart without rebuilding the image.

## Pre-configured Features

The development container includes:

- ✅ Home Assistant (latest version)
- ✅ Admin user (username: `admin`, password: `admin`)
- ✅ Onboarding completed (no setup wizard)
- ✅ Auto-login enabled (trusted networks)
- ✅ HACS 2.0.5 installed and configured
- ✅ HAAnim integration pre-configured
- ✅ Debug logging for HAAnim
- ✅ Live code mounting for development

## Configuration Changes

To modify the pre-configured settings:

1. Edit files in `container-config/`
2. Rebuild the image: `./podman/build-image.sh`
3. Start container: `./podman/build-and-run.sh`

See [container-config/README.md](container-config/README.md) for details on changing passwords,
adding integrations, or modifying settings.

## VS Code Integration

Use VS Code tasks for quick access:

- Press **Ctrl+Shift+B** → Select "Container: Build and Run"
- Or use Command Palette → "Tasks: Run Task"

Available tasks:

- Container: Build and Run
- Container: Start/Stop/Restart
- Container: View Logs
- Open Home Assistant in Browser

## Troubleshooting

### Container won't start

```bash
# Remove old container and rebuild
podman rm -f haanim-dev
./podman/build-and-run.sh
```

### Changes not applying

```bash
# Verify code is mounted
podman inspect haanim-dev | grep -A5 Mounts

# Restart container
./podman/restart.sh
```

### Port already in use

```bash
# Find what's using port 8123
podman ps -a | grep 8123

# Stop conflicting container
podman stop <container-name>
```

For more troubleshooting, see:

- [CONTAINER_DEV.md](../CONTAINER_DEV.md) - Complete container guide
- [PODMAN_INFO.md](PODMAN_INFO.md) - Podman-specific issues

## Additional Resources

- **[../CONTAINER_DEV.md](../CONTAINER_DEV.md)** - Complete development container guide
- **[../QUICKSTART_CONTAINER.md](../QUICKSTART_CONTAINER.md)** - Quick reference
- **[container-config/README.md](container-config/README.md)** - Configuration details
- **[HACS_SETUP.md](HACS_SETUP.md)** - HACS authentication guide
