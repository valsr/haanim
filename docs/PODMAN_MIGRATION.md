# Container-Based Development with Podman/Docker

This document describes the container-based development approach using pre-configured images.

## Current Approach

We use **pre-configured container images** instead of runtime configuration. This provides:

1. **Consistent Development Environment** - Every developer gets the same setup
2. **No Setup Required** - Admin user, HACS, and HAAnim pre-configured
3. **Faster Startup** - No installation scripts needed on container start
4. **Better Reproducibility** - Configuration baked into image at build time

## What We Use

### Container Runtime

The project supports both:

- **Podman** (Recommended) - Rootless, daemonless, more secure
- **Docker** - Traditional container runtime

All scripts auto-detect which one is available.

### Key Files

- **`Dockerfile.dev`** - Defines the pre-configured development image
- **`podman/container-config/`** - Configuration files baked into image
- **`dev/build-and-run.sh`** - One-command build and start script
- **`dev/build-image.sh`** - Build image only
- **`docker-compose.dev.yml`** - Compose file for built image
- **`docker-compose.yml`** - Legacy file (deprecated)

## How to Use

The usage remains the same! All scripts work identically:

```bash
# Build and start (one command - recommended!)
./podman/build-and-run.sh

# Or step by step
./podman/build-image.sh    # Build image
podman start haanim-dev # Start container

# Development workflow
./podman/restart.sh        # Restart after code changes
./podman/logs.sh          # View logs
./podman/stop.sh          # Stop container
```

See [CONTAINER_DEV.md](CONTAINER_DEV.md) or [QUICKSTART.md](QUICKSTART.md) for complete
documentation.

## Why Podman?

Podman offers several advantages over Docker:

1. **Rootless by default** - Better security, no daemon running as root
2. **Daemonless architecture** - No background process required
3. **Docker compatibility** - Same command syntax and API
4. **Better security model** - Uses user namespaces
5. **Systemd integration** - Native service management
6. **SELinux friendly** - Better support for security contexts

## Installation

If you don't have Podman installed yet, see [INSTALL_PODMAN.md](INSTALL_PODMAN.md) for detailed
installation instructions for your platform.

Quick install:

```bash
# Fedora/RHEL/CentOS
sudo dnf install podman

# Ubuntu/Debian
sudo apt install podman

# Arch Linux
sudo pacman -S podman

# macOS
brew install podman
```

## Compatibility Notes

### Volume Mounts

Podman uses SELinux labels on volume mounts (`:z` suffix). This ensures proper access control on
SELinux-enabled systems and doesn't affect non-SELinux systems.

### Images

We use fully qualified image names (`docker.io/homeassistant/home-assistant:latest`) for
better compatibility and explicit registry specification.

### Network Mode

Host network mode works the same way in Podman as in Docker.

### DevContainers

VS Code DevContainers primarily support Docker. For Podman usage, see
`.devcontainer/README.md` for configuration options.

## Backwards Compatibility

If you still want to use Docker, the configuration is compatible! Just use `docker`
instead of `podman`:

```bash
# Works with Docker too
./podman/build-and-run.sh  # Auto-detects docker
```

The scripts automatically detect whether podman or docker is available.

## Troubleshooting

See [dev/PODMAN_INFO.md](podman/PODMAN_INFO.md) for detailed troubleshooting, including:

- Permission issues
- SELinux configuration
- Rootless setup
- Network problems
- Port binding

## Additional Resources

- [Podman Documentation](https://docs.podman.io/)
- [Podman vs Docker](https://docs.podman.io/en/latest/markdown/podman.1.html)
- [Rootless Containers Guide](https://docs.podman.io/en/latest/markdown/podman.1.html#rootless-mode)
- [CONTAINER_DEV.md](CONTAINER_DEV.md) - Complete development container guide
