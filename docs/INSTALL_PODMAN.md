# Installing Podman and podman-compose

This guide helps you install Podman and podman-compose for HAAnim development.

## What is Podman?

Podman is a daemonless container engine that's compatible with Docker. It offers:
- **Rootless operation**: No need for root privileges
- **Security**: Better security model than Docker
- **Compatibility**: Drop-in replacement for Docker commands
- **Systemd integration**: Native service management

## Installation

### Fedora / RHEL / CentOS Stream

```bash
# Install Podman and podman-compose
sudo dnf install -y podman podman-compose

# Enable user lingering (allows containers to run after logout)
loginctl enable-linger $USER
```

### Ubuntu / Debian

```bash
# Ubuntu 20.10 and newer
sudo apt update
sudo apt install -y podman podman-compose

# For older Ubuntu versions, add the repository:
sudo sh -c "echo 'deb http://download.opensuse.org/repositories/devel:/kubic:/libpod:/stable/xUbuntu_${VERSION_ID}/ /' > /etc/apt/sources.list.d/devel:kubic:libpod:stable.list"
wget -nv https://download.opensuse.org/repositories/devel:kubic:libpod:stable/xUbuntu_${VERSION_ID}/Release.key -O- | sudo apt-key add -
sudo apt update
sudo apt install -y podman

# Install podman-compose via pip
pip3 install podman-compose
```

### Arch Linux

```bash
sudo pacman -S podman podman-compose
```

### macOS

```bash
# Install using Homebrew
brew install podman podman-compose

# Initialize Podman machine
podman machine init
podman machine start
```

### Windows

```bash
# Using Windows Subsystem for Linux (WSL2)
# Install WSL2 first, then follow Linux instructions above

# Or use Podman Desktop
# Download from: https://podman-desktop.io/
```

## Verify Installation

```bash
# Check Podman version
podman --version

# Check podman-compose version
podman-compose --version

# Test Podman
podman run hello-world
```

## Configuration for Rootless Mode (Recommended)

```bash
# Enable lingering (keeps services running after logout)
loginctl enable-linger $USER

# Configure subuid/subgid (if not already set)
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER

# Restart Podman to apply changes
podman system migrate
```

## Optional: Docker Compatibility

To use `docker` commands with Podman:

```bash
# Create alias
echo 'alias docker=podman' >> ~/.bashrc
echo 'alias docker-compose=podman-compose' >> ~/.bashrc
source ~/.bashrc
```

Or create symbolic links (requires root):

```bash
sudo ln -s /usr/bin/podman /usr/local/bin/docker
sudo ln -s /usr/bin/podman-compose /usr/local/bin/docker-compose
```

## Troubleshooting

### "permission denied" errors

Make sure you're in the right groups:

```bash
# Add user to groups (may vary by distribution)
sudo usermod -aG podman $USER
newgrp podman
```

### Port binding issues

For ports below 1024 in rootless mode:

```bash
# Allow binding to privileged ports
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/podman-privileged-ports.conf
sudo sysctl -p /etc/sysctl.d/podman-privileged-ports.conf
```

### SELinux issues

If you encounter SELinux problems:

```bash
# Check SELinux status
getenforce

# Allow containers to use host volumes
sudo setsebool -P container_manage_cgroup true
```

## Next Steps

Once Podman is installed:

```bash
# Clone the HAAnim repository
git clone https://github.com/valsr/haanim.git
cd haanim

# Start development environment
./podman/start.sh
```

## Resources

- [Podman Documentation](https://docs.podman.io/)
- [Podman vs Docker](https://docs.podman.io/en/latest/markdown/podman.1.html)
- [podman-compose on GitHub](https://github.com/containers/podman-compose)
- [Rootless Containers](https://docs.podman.io/en/latest/markdown/podman.1.html#rootless-mode)
