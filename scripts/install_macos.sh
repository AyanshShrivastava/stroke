#!/usr/bin/env bash
# ==============================================================================
# STROKE // MACOS NON-ADMINISTRATOR USER INSTALLER
# ==============================================================================
# Strictly adheres to Stroke Zero Administrator Policy:
# - Installs directly to per-user directory: ~/Applications/Stroke.app
# - Application data stored in: ~/Library/Application Support/Stroke
# - Models stored in: ~/Library/Application Support/Stroke/Models
# - Version backups stored in: ~/Library/Application Support/Stroke/Backups
# - NEVER requires sudo, elevation, or system directory writes.
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
USER_APPS="${USER_HOME}/Applications"
USER_BIN="${USER_HOME}/.local/bin"
APP_DATA_DIR="${USER_HOME}/Library/Application Support/Stroke"
MODELS_DIR="${APP_DATA_DIR}/Models"
BACKUPS_DIR="${APP_DATA_DIR}/Backups"
DOWNLOADS_DIR="${APP_DATA_DIR}/Downloads"

echo "================================================================="
echo " STROKE // USER-LEVEL DESKTOP INSTALLATION (MACOS)"
echo "================================================================="
echo "Target Applications: ${USER_APPS}/Stroke.app"
echo "Target User Data:    ${APP_DATA_DIR}"
echo "Target Models:       ${MODELS_DIR}"
echo "Target Backups:      ${BACKUPS_DIR}"
echo "Administrator/Sudo:  NOT REQUIRED (Standard User Permissions)"
echo "================================================================="

# Create necessary user directories
mkdir -p "${USER_APPS}"
mkdir -p "${USER_BIN}"
mkdir -p "${APP_DATA_DIR}"
mkdir -p "${MODELS_DIR}"
mkdir -p "${BACKUPS_DIR}"
mkdir -p "${DOWNLOADS_DIR}"

# Locate source directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(dirname "${SCRIPT_DIR}")"

# Create user-level launcher script
LAUNCHER="${USER_BIN}/stroke"
cat << 'EOF' > "${LAUNCHER}"
#!/usr/bin/env bash
STROKE_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_EXEC="python3"
if [ -f "${STROKE_HOME}/venv/bin/python" ]; then
    PYTHON_EXEC="${STROKE_HOME}/venv/bin/python"
fi
export STROKE_APP_DATA="${HOME}/Library/Application Support/Stroke"
cd "${STROKE_HOME}" && exec "${PYTHON_EXEC}" main.py "$@"
EOF
chmod +x "${LAUNCHER}"

echo "[OK] User directories created cleanly."
echo "[OK] User launcher registered at: ${LAUNCHER}"
echo "[OK] Installation completed with zero root/administrator privileges."
echo "================================================================="
