FROM docker.io/homeassistant/home-assistant:2025.11.3

# Set environment variables
ENV TZ=America/Toronto
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBUGPY_PORT=5678

# Install debugpy for remote debugging
RUN pip install --no-cache-dir debugpy

# Create necessary directories
RUN mkdir -p /config/custom_components \
    && mkdir -p /config/.storage \
    && mkdir -p /config/python_scripts

# Copy configuration files
COPY podman/container-config/configuration.yaml /config/configuration.yaml
COPY podman/container-config/automations.yaml /config/automations.yaml
COPY podman/container-config/scenes.yaml /config/scenes.yaml
COPY podman/container-config/scripts.yaml /config/scripts.yaml

# Copy pre-configured storage files
COPY podman/container-config/.storage/onboarding /config/.storage/onboarding
COPY podman/container-config/.storage/auth /config/.storage/auth
COPY podman/container-config/.storage/auth_provider.homeassistant /config/.storage/auth_provider.homeassistant
COPY podman/container-config/.storage/core.config_entries /config/.storage/core.config_entries
COPY podman/container-config/.storage/frontend.user_data_admin_user_id_12345 /config/.storage/frontend.user_data_admin_user_id_12345

# The still picture of the demo camera (camera.demo), which the dashboard example shows
COPY podman/container-config/demo /config/demo

# A dashboard with the card of each example automation
COPY podman/container-config/ui-lovelace.yaml /config/ui-lovelace.yaml

# The integration requires the haanim package (see its manifest). Install it from this repository, so
# Home Assistant finds the requirement satisfied; start.sh then mounts src/haanim over it with PYTHONPATH,
# which allows live code changes without rebuilding the container.
COPY pyproject.toml README.md LICENSE /opt/haanim-package/
COPY src /opt/haanim-package/src
RUN pip install --no-cache-dir /opt/haanim-package

# Note: the HAAnim integration and the example automations are mounted as volumes from the host

# Set proper permissions
RUN chown -R root:root /config

# Expose ports
EXPOSE 8123
EXPOSE 5678

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8123 || exit 1

# Start Home Assistant with debugpy
# debugpy listens on 5678 and waits for debugger to attach
CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "-m", "homeassistant", "--config", "/config"]
