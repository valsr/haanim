# Podman Development Environment Details

## What's Included

### Container Setup
- **Image**: `docker.io/homeassistant/home-assistant:latest`
- **Container Name**: `haanim-dev`
- **Network**: Host network mode (for device discovery)
- **Timezone**: UTC
- **SELinux**: Volumes labeled with `:z` for proper SELinux context

### Volume Mounts
1. **Custom Component** (live mount):
   - Host: `./custom_components/haanim`
   - Container: `/config/custom_components/haanim:z`
   - Any changes to your code are immediately available in Home Assistant

2. **Development Config** (live mount):
   - Host: `./podman/config`
   - Container: `/config:z`
   - Home Assistant configuration files

3. **Persistent Data** (Podman volume):
   - Volume: `hass-data`
   - Mount: `/config/.storage:z`
   - Persists between container restarts

### Port Mappings
- **8123** → Web UI (http://localhost:8123)

## How It Works

### Starting the Container

When you run `./podman/start.sh`:
1. Podman Compose reads `docker-compose.yml`
2. Pulls the latest Home Assistant image (first time only)
3. Creates a container with mounted volumes
4. Starts Home Assistant
5. Your custom component is automatically available

### File Synchronization

Changes to files in `custom_components/haanim/` are immediately reflected in the container
because of the volume mount. However, Home Assistant needs to be restarted to load code changes.

### Data Persistence

- Configuration and integrations persist in the `hass-data` Podman volume
- Survives container restarts
- To reset completely: `make clean` or `podman-compose down -v`

## Podman vs Docker

Podman is a daemonless container engine that's compatible with Docker:

**Advantages:**
- **Rootless**: Can run containers without root privileges
- **Daemonless**: No background daemon required
- **Docker-compatible**: Uses same command syntax
- **Security**: Better security model with user namespaces
- **Systemd**: Native systemd integration for services

**Key Differences:**
- Uses `podman` instead of `docker` commands
- Uses `podman-compose` instead of `docker-compose`
- Volume mounts need `:z` flag for SELinux labeling
- Fully qualified image names (e.g., `docker.io/...`)

## Configuration

### Home Assistant Config

The `dev/config/configuration.yaml` is configured for development:

```yaml
logger:
  default: info
  logs:
    custom_components.haanim: debug  # Debug logging for your integration
```

### Podman Compose Override

To customize the Podman setup, create `docker-compose.override.yml`:

```yaml
version: '3.8'
services:
  homeassistant:
    environment:
      - CUSTOM_ENV_VAR=value
    ports:
      - "9123:8123"  # Use different port
```

## Advanced Usage

### Access Container Shell

```bash
./podman/shell.sh
# Or: podman-compose exec homeassistant /bin/bash
```

### Check Container Logs

```bash
./podman/logs.sh
# Or: podman-compose logs -f
```

### Inspect Container

```bash
podman inspect haanim-dev
```

### Check Home Assistant Version

```bash
podman-compose exec homeassistant hass --version
```

### Update Home Assistant

```bash
podman-compose pull
podman-compose up -d
```

## Resource Usage

The container typically uses:
- **CPU**: 5-15% (idle), up to 50% (during startup)
- **Memory**: 200-500 MB
- **Disk**: ~1 GB (image + data)

## Troubleshooting

### Container Won't Start

Check Podman:
```bash
podman info
```

Check container status:
```bash
podman ps -a
```

View container logs:
```bash
podman logs haanim-dev
```

### Permission Issues

If you encounter permission errors with SELinux:
```bash
# Linux: Fix SELinux context
restorecon -R dev/config/
# Or run Podman in rootless mode (recommended)
```

For rootless Podman:
```bash
# No sudo needed!
podman-compose up -d
```

### Network Issues

If http://localhost:8123 doesn't work:
- Check if another service uses port 8123
- Try `http://127.0.0.1:8123`
- Check firewall settings
- For rootless Podman, ensure port mapping is working

### Clean Start

To completely reset:
```bash
make clean
# Or manually:
podman-compose down -v
rm -rf dev/config/.storage dev/config/*.db*
./podman/start.sh
```

## Best Practices

1. **Always restart after code changes**: `./podman/restart.sh`
2. **Check logs when debugging**: `./podman/logs.sh`
3. **Use `make clean` to reset state** when testing fresh installs
4. **Keep the image updated**: `podman-compose pull` occasionally
5. **Don't commit dev/config/.storage** to git (already in .gitignore)
6. **Use rootless Podman** for better security (no sudo needed)

## Rootless Podman Setup

Rootless Podman is recommended for development:

```bash
# Install podman (if not already installed)
# Fedora/RHEL: sudo dnf install podman podman-compose
# Debian/Ubuntu: sudo apt install podman podman-compose
# Arch: sudo pacman -S podman podman-compose

# Enable lingering (allows containers to run after logout)
loginctl enable-linger $USER

# Run without sudo
./podman/start.sh
```

Benefits:
- No root privileges required
- Better security isolation
- Each user has their own containers
- Compatible with all scripts

## Security Notes

- Podman provides better security than Docker by default
- Rootless mode isolates containers from the system
- SELinux labels (`:z`) ensure proper access control
- Host network mode exposes Home Assistant to your local network
- Don't use this setup for production - it's for development only
- Don't commit any API keys or secrets in dev/config/

## Performance Tips

- Use `podman-compose restart` instead of `down` + `up` for faster restarts
- The first startup is slow (image download + initialization)
- Subsequent starts are much faster (~10-30 seconds)
- SSD storage significantly improves performance
- Rootless Podman has minimal performance overhead
