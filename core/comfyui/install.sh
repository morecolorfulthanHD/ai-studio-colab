#!/usr/bin/env bash
# AI Studio Colab — ComfyUI install script (Colab-safe, idempotent)
#
# Installs ComfyUI to /content/ComfyUI and symlinks Drive-backed shared models.
# Does not install custom nodes or download model weights.
#
# Usage:
#   bash core/comfyui/install.sh
#   FORCE_REINSTALL=1 bash core/comfyui/install.sh   # remove and re-clone ComfyUI
#
# Environment overrides:
#   COMFYUI_DIR      default: /content/ComfyUI
#   SHARED_MODELS    default: /content/drive/MyDrive/AI_Studio/models/shared
#   COMFYUI_REPO     default: https://github.com/Comfy-Org/ComfyUI.git
#   PYTHON           default: python3

set -euo pipefail

COMFYUI_DIR="${COMFYUI_DIR:-/content/ComfyUI}"
SHARED_MODELS="${SHARED_MODELS:-/content/drive/MyDrive/AI_Studio/models/shared}"
COMFYUI_REPO="${COMFYUI_REPO:-https://github.com/Comfy-Org/ComfyUI.git}"
PYTHON="${PYTHON:-python3}"
FORCE_REINSTALL="${FORCE_REINSTALL:-0}"

log() {
  printf '[comfyui-install] %s\n' "$*"
}

die() {
  printf '[comfyui-install] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

link_shared_models() {
  local models_link="${COMFYUI_DIR}/models"

  if [[ ! -d "${SHARED_MODELS}" ]]; then
    log "Creating shared models directory: ${SHARED_MODELS}"
    mkdir -p "${SHARED_MODELS}"
  fi

  if [[ -L "${models_link}" ]]; then
    local current_target
    current_target="$(readlink -f "${models_link}" 2>/dev/null || readlink "${models_link}")"
    local expected_target
    expected_target="$(readlink -f "${SHARED_MODELS}" 2>/dev/null || echo "${SHARED_MODELS}")"
    if [[ "${current_target}" == "${expected_target}" ]]; then
      log "Models symlink already correct: ${models_link} -> ${SHARED_MODELS}"
      return 0
    fi
    log "Replacing incorrect models symlink: ${models_link}"
    rm -f "${models_link}"
  elif [[ -e "${models_link}" ]]; then
    die "Refusing to replace non-symlink path: ${models_link} (set FORCE_REINSTALL=1 to reinstall ComfyUI)"
  fi

  ln -sfn "${SHARED_MODELS}" "${models_link}"
  log "Linked models: ${models_link} -> ${SHARED_MODELS}"
}

install_comfyui_repo() {
  if [[ "${FORCE_REINSTALL}" == "1" ]]; then
    if [[ -e "${COMFYUI_DIR}" || -L "${COMFYUI_DIR}" ]]; then
      log "FORCE_REINSTALL=1 — removing existing ComfyUI directory: ${COMFYUI_DIR}"
      rm -rf "${COMFYUI_DIR}"
    fi
  fi

  if [[ -d "${COMFYUI_DIR}/.git" ]]; then
    log "ComfyUI already cloned at ${COMFYUI_DIR} — pulling latest changes"
    git -C "${COMFYUI_DIR}" pull --ff-only || log "WARN: git pull failed; continuing with existing clone"
    return 0
  fi

  if [[ -e "${COMFYUI_DIR}" ]]; then
    die "Path exists but is not a ComfyUI git repo: ${COMFYUI_DIR} (use FORCE_REINSTALL=1 to replace)"
  fi

  log "Cloning ComfyUI from ${COMFYUI_REPO}"
  git clone --depth 1 "${COMFYUI_REPO}" "${COMFYUI_DIR}"
}

install_python_requirements() {
  local requirements="${COMFYUI_DIR}/requirements.txt"
  [[ -f "${requirements}" ]] || die "requirements.txt not found: ${requirements}"

  log "Installing Python requirements"
  "${PYTHON}" -m pip install -q -r "${requirements}"
}

main() {
  log "Starting ComfyUI install"
  log "  COMFYUI_DIR=${COMFYUI_DIR}"
  log "  SHARED_MODELS=${SHARED_MODELS}"

  require_cmd git
  require_cmd "${PYTHON}"

  install_comfyui_repo
  install_python_requirements
  link_shared_models

  log "ComfyUI install complete"
  log "  Runtime: ${COMFYUI_DIR}"
  log "  Models:  ${SHARED_MODELS} (symlinked)"
  log "Next: install custom nodes via notebook or future install_nodes.sh"
}

main "$@"
