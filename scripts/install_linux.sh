#!/usr/bin/env bash
# ==============================================================================
# STROKE // LINUX NON-ADMINISTRATOR USER INSTALLER
# ==============================================================================
# Strictly adheres to Stroke Zero Administrator Policy:
# - Installs directly to per-user directory: ~/.local/share/Stroke
# - Binary wrapper installed to: ~/.local/bin/stroke
# - Models stored in: ~/.local/share/Stroke/Models
# - Version backups stored in: ~/.local/share/Stroke/Backups
# - Desktop entry installed to: ~/.local/share/applications/stroke.desktop
# - NEVER requires sudo, elevation, or system root writes.
# ==============================================================================

set -euo pipefail

# Check for root/sudo execution - warn user
if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    echo "[STROKE SECURITY NOTICE] Installer is running as root/sudo."
    echo "[STROKE SECURITY NOTICE] Stroke is designed to run entirely with standard user permissions."
    echo "[STROKE SECURITY NOTICE] It is strongly recommended to run this installer without sudo."
    echo ""
fi

USER_HOME="${HOME:-$(eval echo "~")}"
USER_SHARE="${USER_HOME}/.local/share/Stroke"
USER_BIN="${USER_HOME}/.local/bin"
USER_APPS="${USER_HOME}/.local/share/applications"
MODELS_DIR="${USER_SHARE}/Models"
BACKUPS_DIR="${USER_SHARE}/Backups"
DOWNLOADS_DIR="${USER_SHARE}/Downloads"

echo "================================================================="
echo " STROKE // USER-LEVEL DESKTOP INSTALLATION (LINUX)"
echo "================================================================="
echo "Installation Directory: ${USER_SHARE}"
echo "User Binary:            ${USER_BIN}/stroke"
echo "Models Directory:       ${MODELS_DIR}"
echo "Backups Directory:      ${BACKUPS_DIR}"
echo "Desktop Integration:    ${USER_APPS}/stroke.desktop"
echo "Root / Sudo:            NOT REQUIRED (Standard User Permissions)"
echo "================================================================="

# Create necessary user directories
mkdir -p "${USER_SHARE}"
mkdir -p "${USER_BIN}"
mkdir -p "${USER_APPS}"
mkdir -p "${MODELS_DIR}"
mkdir -p "${BACKUPS_DIR}"
mkdir -p "${DOWNLOADS_DIR}"

# Create user launcher wrapper
cat << 'EOF' > "${USER_BIN}/stroke"
#!/usr/bin/env bash
STROKE_HOME="${HOME}/.local/share/Stroke"
PYTHON_EXEC="python3"
if [ -f "${STROKE_HOME}/venv/bin/python" ]; then
    PYTHON_EXEC="${STROKE_HOME}/venv/bin/python"
fi
export STROKE_APP_DATA="${STROKE_HOME}"
cd "${STROKE_HOME}" && exec "${PYTHON_EXEC}" main.py "$@"
EOF
chmod +x "${USER_BIN}/stroke"

# Create .desktop file for Linux desktop environments (GNOME, KDE, XFCE)
cat << EOF > "${USER_APPS}/stroke.desktop"
[Desktop Entry]
Name=Stroke
Comment=Private AI Coding Assistant & Matrix Operations
Exec=${USER_BIN}/stroke
Icon=utilities-terminal
Terminal=false
Type=Application
Categories=Development;IDE;
StartupNotify=true
EOF

echo "[OK] User directories created cleanly."
echo "[OK] User launcher registered at: ${USER_BIN}/stroke"
echo "[OK] Desktop entry registered at: ${USER_APPS}/stroke.desktop"
echo "[OK] Linux installation completed cleanly with zero root/sudo elevation."
echo "================================================================="
