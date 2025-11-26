# VS Code Quick Reference

## 🚀 Quick Start

**Start Development (One Command):**
```
Press: Ctrl+Shift+B (or Cmd+Shift+B on Mac)
```
This will:
1. Start Home Assistant in Podman
2. Wait for it to be ready
3. Open browser to http://localhost:8123

## ⌨️ Keyboard Shortcuts

| Action                | Windows/Linux                      | Mac           |
| --------------------- | ---------------------------------- | ------------- |
| **Run Build Task**    | `Ctrl+Shift+B`                     | `Cmd+Shift+B` |
| **Run Any Task**      | `Ctrl+Shift+P` → "Tasks: Run Task" | `Cmd+Shift+P` |
| **Start Debugging**   | `F5`                               | `F5`          |
| **Stop Debugging**    | `Shift+F5`                         | `Shift+F5`    |
| **Toggle Breakpoint** | `F9`                               | `F9`          |
| **Open Run & Debug**  | `Ctrl+Shift+D`                     | `Cmd+Shift+D` |

## 📋 Available Tasks

### Development
- **Start Home Assistant** - Starts Podman container
- **Stop Home Assistant** - Stops container
- **Restart Home Assistant** - Restarts after code changes
- **View Logs** - Shows real-time logs
- **Open Shell** - Opens shell in container

### Code Quality
- **Format Code (Black)** - Format Python code
- **Run Tests (pytest)** - Run all tests with coverage
- **Run Linting (Pylint)** - Run code analysis

### Automated
- **Run: Start Dev Environment & Open Browser** ⭐ (Default - `Ctrl+Shift+B`)

## 🐛 Debug Configurations

### Available Configs
1. **Run: Home Assistant Development** ⭐ - Start and open browser
2. **Debug: Attach to Home Assistant Container** - Attach debugger
3. **Debug: Current Python File** - Debug open file
4. **Debug: Pytest Current File** - Debug test file
5. **Debug: All Pytest Tests** - Debug all tests

### Using Debugger
1. Open **Run and Debug** panel (`Ctrl+Shift+D`)
2. Select configuration from dropdown
3. Press `F5` or click green play button

## 🔧 Common Commands

### From VS Code
```
Ctrl+Shift+P → Type command:
  - "Tasks: Run Task" → Select task
  - "Tasks: Run Build Task" (or Ctrl+Shift+B)
  - "Debug: Start Debugging" (or F5)
```

### From Terminal
```bash
make start    # Start Home Assistant
make restart  # Restart after changes
make logs     # View logs
make stop     # Stop container
make test     # Run tests
make format   # Format code
```

## 🎯 Workflow

### Daily Development
1. **Start**: `Ctrl+Shift+B`
2. **Edit**: Make code changes
3. **Test**: Run Task → "Restart Home Assistant"
4. **Verify**: Refresh browser
5. **Commit**: Run Task → "Format Code"

### Debugging
1. Set breakpoints (click line number or `F9`)
2. Select debug config
3. Press `F5`
4. Use `F10` (step over), `F11` (step into)

### Testing
1. Open test file
2. Select "Debug: Pytest Current File"
3. Press `F5`
4. Debug interactively

## 📁 Files

- `.vscode/tasks.json` - Task definitions
- `.vscode/launch.json` - Debug configurations
- `.vscode/settings.json` - VS Code settings
- `VSCODE_TASKS.md` - Full documentation

## 💡 Tips

- **Auto-format**: Code auto-formats on save
- **Build Task**: `Ctrl+Shift+B` is the fastest way to start
- **Logs**: Keep log task running in separate terminal
- **Restart**: Use restart task instead of stop/start
- **Browser**: If browser doesn't open, manually go to http://localhost:8123

## 🔗 Quick Links

- Full Docs: [VSCODE_TASKS.md](VSCODE_TASKS.md)
- Dev Scripts: `dev/*.sh`
- Home Assistant: http://localhost:8123

## 🆘 Troubleshooting

| Problem                | Solution                             |
| ---------------------- | ------------------------------------ |
| Browser doesn't open   | Manually open http://localhost:8123  |
| Container not starting | Check `podman ps` and logs           |
| Task fails             | Run from terminal to see full output |
| Debugger won't attach  | Ensure container is running          |
| Code not updating      | Run "Restart Home Assistant" task    |

---

**Pro Tip**: Press `Ctrl+Shift+B` to start coding in seconds! 🚀
