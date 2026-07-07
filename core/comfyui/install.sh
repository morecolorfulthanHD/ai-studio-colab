#!/usr/bin/env bash
# AI Studio Colab — ComfyUI install/validation script.
#
# Safe by default: dry-run only unless --execute is provided.

set -euo pipefail

COMFYUI_DIR="${COMFYUI_DIR:-/content/ComfyUI}"
SHARED_MODELS="${SHARED_MODELS:-/content/drive/MyDrive/AI_Studio/models/shared}"
COMFYUI_REPO="${COMFYUI_REPO:-https://github.com/Comfy-Org/ComfyUI.git}"
PYTHON="${PYTHON:-python3}"
FORCE_REINSTALL=0
EXECUTE=0

log() {
  printf '[comfyui-install] %s\n' "$*"
}

die() {
  printf '[comfyui-install] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage:
  bash core/comfyui/install.sh [--dry-run] [--execute] [--force-reinstall]

Modes:
  --dry-run         Print planned actions only (default)
  --execute         Apply changes (clone/pull, pip install, symlink)
  --force-reinstall Remove existing COMFYUI_DIR before clone (only with --execute)
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

run_step() {
  if [[ "${EXECUTE}" == "1" ]]; then
    log "EXECUTE: $*"
    "$@"
  else
    log "DRY-RUN: $*"
  fi
}

link_shared_models() {
  local models_link="${COMFYUI_DIR}/models"

  if [[ ! -d "${SHARED_MODELS}" ]]; then
    run_step mkdir -p "${SHARED_MODELS}"
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
    die "Refusing to replace non-symlink path: ${models_link} (use --force-reinstall with --execute if you intend replacement)"
  fi

  run_step ln -sfn "${SHARED_MODELS}" "${models_link}"
  log "Linked models: ${models_link} -> ${SHARED_MODELS}"
}

install_comfyui_repo() {
  if [[ "${FORCE_REINSTALL}" == "1" ]]; then
    if [[ -e "${COMFYUI_DIR}" || -L "${COMFYUI_DIR}" ]]; then
      run_step rm -rf "${COMFYUI_DIR}"
    fi
  fi

  if [[ -d "${COMFYUI_DIR}/.git" ]]; then
    if [[ "${EXECUTE}" == "1" ]]; then
      log "ComfyUI already cloned at ${COMFYUI_DIR} — pulling latest changes"
      git -C "${COMFYUI_DIR}" pull --ff-only
    else
      log "DRY-RUN: would pull latest changes in ${COMFYUI_DIR}"
    fi
    return 0
  fi

  if [[ -e "${COMFYUI_DIR}" ]]; then
    die "Path exists but is not a ComfyUI git repo: ${COMFYUI_DIR} (use FORCE_REINSTALL=1 to replace)"
  fi

  run_step git clone --depth 1 "${COMFYUI_REPO}" "${COMFYUI_DIR}"
}

install_python_requirements() {
  local requirements="${COMFYUI_DIR}/requirements.txt"
  if [[ ! -f "${requirements}" ]]; then
    if [[ "${EXECUTE}" == "1" ]]; then
      die "requirements.txt not found: ${requirements}"
    fi
    log "DRY-RUN: requirements path not present yet (${requirements})"
    return 0
  fi
  run_step "${PYTHON}" -m pip install -q -r "${requirements}"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        EXECUTE=0
        ;;
      --execute)
        EXECUTE=1
        ;;
      --force-reinstall)
        FORCE_REINSTALL=1
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
    shift
  done

  if [[ "${FORCE_REINSTALL}" == "1" && "${EXECUTE}" != "1" ]]; then
    die "--force-reinstall requires --execute"
  fi
}

main() {
  parse_args "$@"
  log "Starting ComfyUI install/validation"
  if [[ "${EXECUTE}" == "1" ]]; then
    log "  mode=execute"
  else
    log "  mode=dry-run"
  fi
  log "  COMFYUI_DIR=${COMFYUI_DIR}"
  log "  SHARED_MODELS=${SHARED_MODELS}"

  require_cmd git
  require_cmd "${PYTHON}"

  install_comfyui_repo
  install_python_requirements
  link_shared_models

  log "ComfyUI install/validation complete"
  log "  Runtime: ${COMFYUI_DIR}"
  log "  Models:  ${SHARED_MODELS} (symlinked)"
  log "Next: install or validate custom nodes via install_nodes.py"
}

main "$@"
