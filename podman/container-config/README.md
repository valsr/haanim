# Container Configuration Files

This directory contains pre-configured Home Assistant files that are baked into the development
container image.

## Purpose

These files are copied into the container during the Docker build process to provide a fully
configured Home Assistant instance with:

- Completed onboarding
- Admin user (admin/admin)
- HAAnim integration pre-configured (volume-mounted from host)
- Trusted networks for auto-login

## HAAnim Development Setup

The HAAnim integration is **mounted as a volume** from the host, not copied into the image. This
means:

✅ **Live Code Changes** - Edit files on your host and changes are immediately available in the
   container
✅ **No Rebuild Needed** - Just restart Home Assistant to reload the integration
✅ **Real-time Development** - Fast iteration without Docker rebuilds

To reload HAAnim after making changes:

```bash
podman restart haanim-dev
# or use VS Code task: "Restart Home Assistant"
```

## Files

### Configuration Files

- **configuration.yaml** - Main Home Assistant configuration
  - Trusted networks enabled (auto-login)
  - Debug logging for HAAnim
  - Basic integrations enabled

- **automations.yaml** - Empty automations file
- **scenes.yaml** - Empty scenes file
- **scripts.yaml** - Empty scripts file

### Storage Files (.storage/)

These are Home Assistant's internal storage files:

- **onboarding** - Marks onboarding as complete
- **auth** - User definitions (admin user)
- **auth_provider.homeassistant** - Password hashes (admin:admin)
- **core.config_entries** - Pre-configured integrations (HAAnim)
- **frontend.user_data_admin_user_id_12345** - Frontend user preferences

## Modifying Configuration

To change the container's default configuration:

1. Edit files in this directory
2. Rebuild the image:

   ```bash
   ./dev/build-image.sh
   ```

### Changing Admin Password

1. Generate new bcrypt hash:

   ```bash
   python3 -c "import bcrypt; print(bcrypt.hashpw('your_password'.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8'))"
   ```

2. Update `.storage/auth_provider.homeassistant` with the new hash

3. Rebuild the image

### Adding Pre-configured Integrations

Add entries to `.storage/core.config_entries`:

```json
{
  "entry_id": "unique_id_here",
  "version": 1,
  "minor_version": 1,
  "domain": "integration_domain",
  "title": "Integration Title",
  "data": {},
  "options": {},
  "pref_disable_new_entities": false,
  "pref_disable_polling": false,
  "source": "user",
  "unique_id": null,
  "disabled_by": null,
  "created_at": "2024-01-01T00:00:00.000000+00:00",
  "modified_at": "2024-01-01T00:00:00.000000+00:00"
}
```

## Notes

- Storage files must be valid JSON
- Changes require image rebuild to take effect
- Runtime changes are lost when container is recreated
- For persistent changes, mount a volume or rebuild the image

## Security

⚠️ **Development Only**: These configurations bypass security for development convenience:

- Weak password (admin/admin)
- Trusted networks accept all IPs (0.0.0.0/0)

**Never use this configuration in production!**
