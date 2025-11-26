# VS Code DevContainer with Podman

This project includes a DevContainer configuration for VS Code development.

## Using with Podman

VS Code's Dev Containers extension primarily supports Docker, but can work with Podman with
additional configuration:

### Option 1: Docker Socket Emulation (Recommended)

Create a Docker socket alias for Podman:

```bash
# On Linux
systemctl --user enable --now podman.socket
export DOCKER_HOST=unix:///run/user/$UID/podman/podman.sock

# Add to your shell profile (~/.bashrc or ~/.zshrc)
echo 'export DOCKER_HOST=unix:///run/user/$UID/podman/podman.sock' >> ~/.bashrc
```

Then open the project in VS Code and use "Reopen in Container".

### Option 2: Use Podman Directly

1. Install VS Code extension: "Podman Desktop"
2. Configure VS Code to use Podman instead of Docker
3. Open the project and use "Reopen in Container"

### Option 3: Use the Scripts Instead

If DevContainer setup is complex, simply use the development scripts:

```bash
# Start Home Assistant
./podman/start.sh

# Open VS Code normally (not in container)
code .

# Your custom component is still live-mounted
# Just restart after changes: ./podman/restart.sh
```

This gives you most benefits without container-in-container complexity.

## Configuration

The `.devcontainer/devcontainer.json` file configures:
- Python development environment
- Extensions (Pylance, Black formatter, YAML support)
- Code formatting on save
- Line length limits (110 characters)

## Troubleshooting

If DevContainer fails to start:
- Check that Podman is running: `podman ps`
- Try the Docker socket emulation method
- Use the development scripts instead (Option 3 above)
- Check VS Code DevContainer logs: Command Palette → "Dev Containers: Show Container Log"

## Note

The devcontainer configuration is compatible with both Docker and Podman. If you have Docker
installed, it will work out of the box. For Podman, follow one of the options above.
