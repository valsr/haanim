# VS Code Tasks and Debug Configuration

This document explains how to use the VS Code tasks and debug configurations for HAAnim development.

## Quick Start

### One-Command Development

1. Press **`Ctrl+Shift+B`** (or **`Cmd+Shift+B`** on Mac)
2. This runs "Container: Build and Run" which:
   - Builds the pre-configured development image
   - Starts the container with your code mounted
   - Opens your browser automatically

Or use the Command Palette:

1. Press **`Ctrl+Shift+P`** (or **`Cmd+Shift+P`** on Mac)
2. Type **"Tasks: Run Task"**
3. Select **"Container: Build and Run"**

### Using the Run and Debug Panel

1. Go to the **Run and Debug** view (Ctrl+Shift+D)
2. Select a debug configuration from the dropdown
3. Press **F5** or click the green play button

## Available Tasks

### Container Management Tasks

#### Container: Build and Run ⭐ (Default)

- **Shortcut**: **`Ctrl+Shift+B`**
- **Command**: `./podman/build-and-run.sh`
- **Description**: Complete one-command setup that:
  - Builds the pre-configured image (first time ~5 minutes)
  - Stops and removes any existing container
  - Starts fresh container with code mounted
  - Waits for Home Assistant to start
  - Opens browser automatically
- **Use when**: Starting development or after major changes

#### Container: Build Image

- **Command**: `./podman/build-image.sh`
- **Description**: Builds the development image without starting it
- **Use when**: You want to rebuild after configuration changes

#### Container: Start

- **Command**: `podman start haanim-dev` (or `docker start`)
- **Description**: Starts an existing stopped container
- **Use when**: Container is built but stopped

#### Container: Stop

- **Command**: `./podman/stop.sh`
- **Description**: Stops the running container
- **Use when**: Done developing or need to free resources

#### Container: Restart

- **Command**: `./podman/restart.sh`
- **Description**: Restarts the container to apply code changes
- **Use when**: After editing code in `custom_components/haanim/`

#### Container: View Logs

- **Command**: `./podman/logs.sh`
- **Description**: Shows real-time logs from the container
- **Access**: Terminal > Run Task > "Container: View Logs"
- **Note**: Press Ctrl+C to stop viewing logs

#### Container: Open Shell

- **Command**: `./podman/shell.sh`
- **Description**: Opens a shell inside the running container
- **Use when**: Need to inspect container internals or run commands

### Browser Task

#### Open Home Assistant in Browser

- **Description**: Opens Home Assistant dashboard in your default browser
- **URL**: <http://localhost:8123>
- **Use when**: Manually want to open the browser

### Code Quality Tasks

#### Format Code (Black)
- **Command**: `uv run black --line-length 110 custom_components/haanim/`
- **Description**: Formats Python code using Black
- **Access**: Terminal > Run Task > "Format Code (Black)"

#### Run Tests (pytest)
- **Command**: `uv run pytest -v --cov=custom_components/haanim`
- **Description**: Runs all tests with coverage
- **Access**: Terminal > Run Task > "Run Tests (pytest)"
- **Shortcut**: Can also use Test Explorer

#### Run Linting (Pylint)
- **Command**: `uv run pylint custom_components/haanim/`
- **Description**: Runs Pylint code analysis
- **Access**: Terminal > Run Task > "Run Linting (Pylint)"

## Debug Configurations

### Run: Home Assistant Development
- **Type**: Node (triggers tasks)
- **Description**: Starts Home Assistant and opens browser
- **Usage**:
  1. Open Run and Debug panel (Ctrl+Shift+D)
  2. Select this configuration
  3. Press F5
- **Note**: This is the primary way to run the project in VS Code

### Debug: Attach to Home Assistant Container
- **Type**: Python Debugger (debugpy)
- **Description**: Attaches debugger to running Home Assistant
- **Port**: 5678
- **Prerequisites**:
  1. Home Assistant must be running
  2. Debugpy must be installed in the container
  3. Home Assistant must be started with debugpy enabled
- **Path Mapping**: Automatically maps local code to container paths

### Debug: Current Python File
- **Type**: Python Debugger (debugpy)
- **Description**: Runs and debugs the currently open Python file
- **Usage**:
  1. Open a Python file
  2. Set breakpoints
  3. Press F5 with this config selected

### Debug: Pytest Current File
- **Type**: Python Debugger (debugpy)
- **Description**: Runs and debugs tests in the current file
- **Usage**:
  1. Open a test file (test_*.py)
  2. Set breakpoints
  3. Press F5 with this config selected

### Debug: All Pytest Tests
- **Type**: Python Debugger (debugpy)
- **Description**: Runs and debugs all tests
- **Usage**: Select this config and press F5

## Keyboard Shortcuts

| Action            | Shortcut                           |
| ----------------- | ---------------------------------- |
| Run Build Task    | `Ctrl+Shift+B`                     |
| Run Task          | `Ctrl+Shift+P` → "Tasks: Run Task" |
| Start Debugging   | `F5`                               |
| Stop Debugging    | `Shift+F5`                         |
| Restart Debugging | `Ctrl+Shift+F5`                    |
| Toggle Breakpoint | `F9`                               |
| Step Over         | `F10`                              |
| Step Into         | `F11`                              |
| Step Out          | `Shift+F11`                        |

## Common Workflows

### Starting Development

1. **Initial Setup** (First time only):

   ```bash
   # One-time setup
   make install
   make dev
   ```

2. **Build and Start Container**:
   - Press `Ctrl+Shift+B` (runs "Container: Build and Run")
   - Or: Terminal > Run Task > "Container: Build and Run"
   - Or from terminal: `./podman/build-and-run.sh`

3. **Make Changes**:
   - Edit code in `custom_components/haanim/`
   - Save files (auto-formatted on save)

4. **Apply Changes**:
   - Terminal > Run Task > "Container: Restart"
   - Or run: `./podman/restart.sh`
   - Refresh browser to see changes

### Testing Workflow

1. **Run All Tests**:
   - Terminal > Run Task > "Run Tests (pytest)"
   - Or: `make test`

2. **Debug Specific Test**:
   - Open test file
   - Set breakpoints
   - Select "Debug: Pytest Current File"
   - Press F5

3. **Format Before Commit**:
   - Terminal > Run Task > "Format Code (Black)"
   - Or: `make format`

### Debugging Workflow

1. **Debug Python Code Directly**:
   - Open Python file
   - Set breakpoints (click line number)
   - Select "Debug: Current Python File"
   - Press F5

2. **Debug in Container** (Advanced):
   - Requires debugpy in container
   - Start Home Assistant with debugpy enabled
   - Select "Debug: Attach to Home Assistant Container"
   - Press F5
   - Set breakpoints in your integration code

## Task Configuration Details

### Task Groups

Tasks are organized into groups:
- **Build**: Development environment tasks
- **Test**: Testing tasks
- **Default**: The main run task is the default build task

### Presentation Settings

- **reveal**: "always" - Shows terminal output
- **panel**: "dedicated" - Uses separate terminal per task
- **focus**: false - Doesn't steal focus automatically
- **clear**: true - Clears terminal before running

### Problem Matchers

Most tasks use `"problemMatcher": []` to prevent VS Code from trying to parse output for errors. You can customize this for better integration.

## Customization

### Adding Custom Tasks

Edit `.vscode/tasks.json`:

```json
{
  "label": "My Custom Task",
  "type": "shell",
  "command": "echo 'Hello World'",
  "problemMatcher": []
}
```

### Modifying Existing Tasks

1. Open `.vscode/tasks.json`
2. Find the task by label
3. Modify command, args, or presentation

### Custom Keyboard Shortcuts

Add to `.vscode/keybindings.json`:

```json
[
  {
    "key": "ctrl+shift+h",
    "command": "workbench.action.tasks.runTask",
    "args": "Start Home Assistant (Podman)"
  }
]
```

## Troubleshooting

### Browser Doesn't Open

**Problem**: Task completes but browser doesn't open

**Solutions**:

1. Check if Home Assistant is running: `podman ps`
2. Manually open: <http://localhost:8123>
3. Check browser command in task (xdg-open/open/start)

### Home Assistant Not Ready

**Problem**: Browser opens but shows "Can't connect"

**Solutions**:

1. Wait 1-2 minutes for Home Assistant to fully start
2. Check logs: Terminal > Run Task > "Container: View Logs"
3. Verify container is running: `podman ps`
4. Check port: `curl http://localhost:8123`

### Task Fails to Run

**Problem**: Task execution fails

**Solutions**:

1. Check Podman/Docker is installed: `podman --version` or `docker --version`
2. Check scripts are executable: `chmod +x dev/*.sh`
3. Check script paths in tasks.json
4. Try rebuilding: `./podman/build-image.sh`

### Container Won't Start

**Problem**: Build succeeds but container fails to start

**Solutions**:

1. Remove old container: `podman rm -f haanim-dev`
2. Check port 8123 is free: `podman ps -a | grep 8123`
3. Rebuild and start: `./podman/build-and-run.sh`

### Debug Attachment Fails

**Problem**: Cannot attach debugger to container

**Solutions**:

1. Ensure Home Assistant is running
2. Debugpy must be installed in container
3. Home Assistant must be started with debugpy enabled
4. Check port 5678 is exposed in docker-compose.yml

### UV Commands Not Working

**Problem**: UV tasks fail

**Solutions**:

1. Install UV: `make install`
2. Sync dependencies: `uv sync --all-extras`
3. Check UV is in PATH: `uv --version`

## Best Practices

1. **Use the Default Build Task**: Press `Ctrl+Shift+B` for quick build and start
2. **View Logs Regularly**: Keep log task running in separate terminal
3. **Restart After Code Changes**: Use restart task, no need to rebuild
4. **Rebuild After Config Changes**: Config changes need image rebuild
5. **Format Before Commit**: Run format task or `make format`
6. **Run Tests Often**: Use test tasks to catch issues early

## Quick Reference

### Most Used Commands

```bash
# Start and open browser (from VS Code)
Ctrl+Shift+B                # Default build task

# Or from terminal
./podman/build-and-run.sh      # Build and start (one command)
./podman/restart.sh            # Restart after code changes
./podman/logs.sh               # View logs
./podman/stop.sh               # Stop container
./podman/build-image.sh        # Rebuild image

# Code quality
make format                 # Format code
make test                   # Run tests
make lint                   # Run linters
```

### URLs

- **Home Assistant UI**: <http://localhost:8123>
- **Admin Credentials**: username `admin`, password `admin` (auto-login enabled)
- **Container Name**: haanim-dev

### Files

- **Tasks**: `.vscode/tasks.json`
- **Debug**: `.vscode/launch.json`
- **Settings**: `.vscode/settings.json`
- **Image Build**: `Dockerfile.dev`
- **Container Config**: `podman/container-config/`
- **Scripts**: `dev/*.sh`

## Additional Resources

- [CONTAINER_DEV.md](CONTAINER_DEV.md) - Complete container development guide
- [QUICKSTART_CONTAINER.md](QUICKSTART_CONTAINER.md) - Quick start reference
- [VS Code Tasks Documentation](https://code.visualstudio.com/docs/editor/tasks)
- [VS Code Debugging Documentation](https://code.visualstudio.com/docs/editor/debugging)
- [Python Debugging in VS Code](https://code.visualstudio.com/docs/python/debugging)
