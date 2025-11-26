# HAAnim Development Container - Quick Start

## What You Get

A fully pre-configured Home Assistant development container with:

- ✅ Home Assistant latest version
- ✅ Admin user pre-configured (username: `admin`, password: `admin`)
- ✅ Onboarding completed (no setup wizard)
- ✅ Auto-login enabled (no password prompt)
- ✅ HACS 2.0.5 installed and configured
- ✅ HAAnim integration pre-configured
- ✅ Live code mounting (changes apply on restart)
- ✅ Debug logging enabled for HAAnim

## One-Command Start

```bash
./podman/build-and-run.sh
```

This will:

1. Build the `haanim-dev:latest` image (first time only, ~5 minutes)
2. Start the container with name `haanim-dev`
3. Mount your code for live development
4. Wait for Home Assistant to start
5. Open your browser to <http://localhost:8123>

You'll be automatically logged in as `admin` - no credentials needed!

## Development Workflow

### Make Code Changes

Edit files in `custom_components/haanim/`:

```bash
# Your changes are live-mounted in the container
vim custom_components/haanim/sensor.py
```

### Apply Changes

```bash
# Restart the container to apply changes
podman restart haanim-dev

# Or rebuild if you changed container config
./podman/build-and-run.sh
```

### View Logs

```bash
# Follow all logs
podman logs -f haanim-dev

# Just HAAnim logs
podman logs haanim-dev 2>&1 | grep haanim
```

### Stop Container

```bash
podman stop haanim-dev
```

## VS Code Integration

Use Ctrl+Shift+B (default build task) or select from tasks:

- **Container: Build and Run** - Build image and start container
- **Container: Start** - Start existing container
- **Container: Stop** - Stop container
- **Container: Restart** - Restart container
- **Container: Logs** - View logs
- **Open Home Assistant in Browser** - Open browser

## What's Pre-configured

### Storage Files

All configuration is baked into the image at build time:

- `.storage/onboarding` - Marks setup complete
- `.storage/auth` - Admin user definition
- `.storage/auth_provider.homeassistant` - Password hash
- `.storage/core.config_entries` - HACS and HAAnim integrations

**Note:** HACS creates its own storage files automatically on first run. We pre-configure the
HACS config entry, which triggers HACS to initialize itself properly.

### Configuration

- **Trusted Networks**: All IPs allowed (0.0.0.0/0) for development
- **Auto-login**: No password required
- **Debug Logging**: HAAnim component logs at debug level
- **HACS**: Fully enabled and configured as an integration (appears in sidebar)

## Credentials

```text
Username: admin
Password: admin
```

(Auto-login is enabled, so you won't need these)

## URLs

- Home Assistant: <http://localhost:8123>
- Configuration: <http://localhost:8123/config>
- Integrations: <http://localhost:8123/config/integrations>
- HACS: <http://localhost:8123/hacs> (in sidebar)

## Troubleshooting

### Container Won't Start

```bash
# Check if port 8123 is in use
podman ps -a | grep 8123

# Remove old container
podman rm -f haanim-dev

# Rebuild and start
./podman/build-and-run.sh
```

### Changes Not Applying

```bash
# Ensure code is mounted correctly
podman inspect haanim-dev | grep -A5 Mounts

# Should show: custom_components/haanim mounted to /config/custom_components/haanim
```

### Integration Not Showing

1. Check Devices & Services: <http://localhost:8123/config/integrations>
2. Look for "HAAnim" in the list
3. If missing, rebuild image: `./podman/build-and-run.sh`
4. Check logs: `podman logs haanim-dev 2>&1 | grep -i haanim`

### HACS Not Appearing

HACS should appear in the sidebar automatically.

**If HACS is missing:**

1. Check Devices & Services - HACS should be listed as an integration
2. Check sidebar - HACS panel should be visible
3. Check logs: `podman logs haanim-dev 2>&1 | grep -i hacs`
4. Rebuild if needed: `./podman/build-and-run.sh`

**Note:** HACS is fully configured and functional. You may need GitHub authentication to
download some repositories, but the integration itself is ready to use.

## Next Steps

1. **Build and Start**: Run `./podman/build-and-run.sh`
2. **Verify Setup**: Check that you're auto-logged in as admin
3. **Check HACS**: Look for HACS in the sidebar (should be there!)
4. **Verify Integration**: Go to Devices & Services, find HACS and HAAnim
5. **Start Coding**: Make changes to `custom_components/haanim/`
6. **Test Changes**: Restart container and verify

## Documentation

- **Full Container Guide**: See [CONTAINER_DEV.md](CONTAINER_DEV.md)
- **Container Config**: See [podman/container-config/README.md](podman/container-config/README.md)
- **HACS Integration**: See [HACS_INTEGRATION.md](HACS_INTEGRATION.md)
- **General Quickstart**: See [QUICKSTART.md](QUICKSTART.md)

## Security Warning

⚠️ **This configuration is for DEVELOPMENT ONLY**

- Weak credentials (admin/admin)
- All networks trusted (0.0.0.0/0)
- Auto-login enabled

**Never use this in production!**
