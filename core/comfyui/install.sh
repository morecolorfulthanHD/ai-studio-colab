#!/usr/bin/env bash
# AI Studio Colab — ComfyUI install/validation script.
#
# Safe by default: dry-run only unless --execute is provided.
# Persistent Drive models are exposed via extra_model_paths.yaml.
# The native ComfyUI models/ directory is never replaced or deleted.

set -Eeuo pipefail

COMFYUI_DIR="${COMFYUI_DIR:-/content/ComfyUI}"
SHARED_MODELS="${SHARED_MODELS:-/content/drive/MyDrive/AI_Studio/models/shared}"
AI_STUDIO_ROOT="${AI_STUDIO_ROOT:-/content/drive/MyDrive/AI_Studio}"
DRIVE_MY_DRIVE="${DRIVE_MY_DRIVE:-/content/drive/MyDrive}"
COMFYUI_REPO="${COMFYUI_REPO:-https://github.com/Comfy-Org/ComfyUI.git}"
PYTHON="${PYTHON:-python3}"
EXTRA_MODEL_PATHS_FILE="${EXTRA_MODEL_PATHS_FILE:-${COMFYUI_DIR}/extra_model_paths.yaml}"
FORCE_REINSTALL=0
EXECUTE=0

SHARED_MODEL_SUBDIRS=(
  checkpoints
  controlnet
  loras
  vae
  embeddings
  upscale_models
  clip
  ipadapter
  animatediff
  insightface
  svd
)

on_err() {
  local exit_code=$?
  local line_no=${BASH_LINENO[0]:-unknown}
  local cmd=${BASH_COMMAND:-unknown}
  printf '[comfyui-install] FATAL: command failed\n' >&2
  printf '[comfyui-install]   command: %s\n' "${cmd}" >&2
  printf '[comfyui-install]   line:    %s\n' "${line_no}" >&2
  printf '[comfyui-install]   exit:    %s\n' "${exit_code}" >&2
  exit "${exit_code}"
}
trap on_err ERR

log() {
  printf '[comfyui-install] %s\n' "$*"
}

phase() {
  printf '\n[comfyui-install] === %s ===\n' "$*"
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
  --execute         Apply changes (clone/pull, pip install, extra_model_paths.yaml)
  --force-reinstall Remove existing COMFYUI_DIR before clone (only with --execute)

Notes:
  Persistent Drive models are configured via ${EXTRA_MODEL_PATHS_FILE}.
  The native ${COMFYUI_DIR}/models directory is preserved.
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

resolve_path() {
  local path="$1"
  if command -v readlink >/dev/null 2>&1; then
    readlink -f "${path}" 2>/dev/null || printf '%s' "${path}"
  else
    printf '%s' "${path}"
  fi
}

validate_tools() {
  phase "Validate tools"
  require_cmd git
  require_cmd "${PYTHON}"
  log "git:    $(command -v git)"
  log "python: $(command -v "${PYTHON}")"
  if ! "${PYTHON}" -c 'import sys; print(sys.version.split()[0])' >/dev/null 2>&1; then
    die "Python interpreter is not usable: ${PYTHON}"
  fi
  log "python version: $("${PYTHON}" -c 'import sys; print(sys.version.split()[0])')"
}

ensure_shared_model_subdirs() {
  local subdir
  for subdir in "${SHARED_MODEL_SUBDIRS[@]}"; do
    local target="${SHARED_MODELS}/${subdir}"
    if [[ -d "${target}" ]]; then
      log "Shared subdir OK: ${target}"
    elif [[ "${EXECUTE}" == "1" ]]; then
      run_step mkdir -p "${target}"
      log "Created shared subdir: ${target}"
    else
      log "DRY-RUN: would create shared subdir: ${target}"
    fi
  done
}

validate_drive_layout() {
  phase "Validate Google Drive layout"

  if [[ ! -d "${DRIVE_MY_DRIVE}" ]]; then
    die "Google Drive is not mounted (${DRIVE_MY_DRIVE} missing). Run the Drive mount cell before ComfyUI install."
  fi
  log "Drive mount OK: ${DRIVE_MY_DRIVE}"

  if [[ ! -d "${AI_STUDIO_ROOT}" ]]; then
    log "AI Studio root missing: ${AI_STUDIO_ROOT}"
    if [[ "${EXECUTE}" == "1" ]]; then
      run_step mkdir -p "${AI_STUDIO_ROOT}"
      log "Created AI Studio root: ${AI_STUDIO_ROOT}"
    else
      log "DRY-RUN: would create AI Studio root: ${AI_STUDIO_ROOT}"
    fi
  else
    log "AI Studio root OK: ${AI_STUDIO_ROOT}"
  fi

  if [[ ! -d "${SHARED_MODELS}" ]]; then
    log "Shared models directory missing: ${SHARED_MODELS}"
    if [[ "${EXECUTE}" == "1" ]]; then
      run_step mkdir -p "${SHARED_MODELS}"
      log "Created shared models directory: ${SHARED_MODELS}"
    else
      log "DRY-RUN: would create shared models directory: ${SHARED_MODELS}"
    fi
  else
    log "Shared models directory OK: ${SHARED_MODELS}"
  fi

  ensure_shared_model_subdirs
}

describe_comfyui_state() {
  phase "Inspect ComfyUI runtime path"

  if [[ ! -e "${COMFYUI_DIR}" && ! -L "${COMFYUI_DIR}" ]]; then
    log "ComfyUI state: missing (${COMFYUI_DIR})"
    return 0
  fi

  if [[ -d "${COMFYUI_DIR}/.git" ]]; then
    log "ComfyUI state: valid git repo (${COMFYUI_DIR})"
    if [[ "${EXECUTE}" == "1" ]]; then
      log "git remote: $(git -C "${COMFYUI_DIR}" remote get-url origin 2>/dev/null || echo unknown)"
      log "git HEAD:   $(git -C "${COMFYUI_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    fi
    return 0
  fi

  if [[ -d "${COMFYUI_DIR}" ]]; then
    die "ComfyUI state: invalid non-git directory at ${COMFYUI_DIR}. Use --force-reinstall --execute to replace."
  fi

  if [[ -L "${COMFYUI_DIR}" ]]; then
    die "ComfyUI state: symlink at ${COMFYUI_DIR} (expected git clone directory). Use --force-reinstall --execute to replace."
  fi

  die "ComfyUI state: unknown existing path at ${COMFYUI_DIR}"
}

describe_native_models_directory() {
  local models_dir="${COMFYUI_DIR}/models"

  phase "Inspect native ComfyUI models directory"
  log "Native models path: ${models_dir}"

  if [[ -d "${models_dir}" && ! -L "${models_dir}" ]]; then
    log "Native models directory present (kept intact)."
    return 0
  fi

  if [[ -L "${models_dir}" ]]; then
    log "Legacy models symlink detected (kept): ${models_dir} -> $(readlink "${models_dir}" 2>/dev/null || echo unknown)"
    log "Persistent Drive models are configured separately via extra_model_paths.yaml."
    return 0
  fi

  if [[ ! -e "${models_dir}" ]]; then
    log "Native models directory not present yet (ComfyUI may create it on first run)."
    return 0
  fi

  log "Native models path exists as a non-directory file: ${models_dir}"
}

generate_ai_studio_extra_paths_block() {
  cat <<EOF
# BEGIN AI_STUDIO_MANAGED
# AI Studio Colab — persistent Google Drive model paths (managed by install.sh)
ai_studio_drive:
    base_path: ${SHARED_MODELS}
    is_default: true
    checkpoints: checkpoints
    controlnet: controlnet
    loras: loras
    vae: vae
    embeddings: embeddings
    upscale_models: upscale_models
    clip: clip
    ipadapter: ipadapter
# END AI_STUDIO_MANAGED
EOF
}

manage_extra_model_paths() {
  local block action

  phase "Configure ComfyUI extra model paths"
  describe_native_models_directory

  log "Extra model paths file: ${EXTRA_MODEL_PATHS_FILE}"
  log "Drive model root:       ${SHARED_MODELS}"

  block="$(generate_ai_studio_extra_paths_block)"

  if [[ "${EXECUTE}" != "1" ]]; then
  action="$("${PYTHON}" - "${EXTRA_MODEL_PATHS_FILE}" "${SHARED_MODELS}" <<'PY'
import pathlib
import re
import sys

config_path = pathlib.Path(sys.argv[1])
shared_models = sys.argv[2]
block = f"""# BEGIN AI_STUDIO_MANAGED
# AI Studio Colab — persistent Google Drive model paths (managed by install.sh)
ai_studio_drive:
    base_path: {shared_models}
    is_default: true
    checkpoints: checkpoints
    controlnet: controlnet
    loras: loras
    vae: vae
    embeddings: embeddings
    upscale_models: upscale_models
    clip: clip
    ipadapter: ipadapter
# END AI_STUDIO_MANAGED"""

if not config_path.exists():
    print("would_create")
    raise SystemExit(0)

text = config_path.read_text(encoding="utf-8")
if "BEGIN AI_STUDIO_MANAGED" not in text:
    print("user_managed")
    raise SystemExit(0)

pattern = r"# BEGIN AI_STUDIO_MANAGED.*?# END AI_STUDIO_MANAGED"
new_text = re.sub(pattern, block.strip(), text, count=1, flags=re.DOTALL)
if new_text == text:
    print("unchanged")
else:
    print("would_update")
PY
)"
    log "DRY-RUN: extra model paths action: ${action}"
    return 0
  fi

  action="$("${PYTHON}" - "${EXTRA_MODEL_PATHS_FILE}" "${SHARED_MODELS}" <<'PY'
import pathlib
import re
import sys

config_path = pathlib.Path(sys.argv[1])
shared_models = sys.argv[2]
block = f"""# BEGIN AI_STUDIO_MANAGED
# AI Studio Colab — persistent Google Drive model paths (managed by install.sh)
ai_studio_drive:
    base_path: {shared_models}
    is_default: true
    checkpoints: checkpoints
    controlnet: controlnet
    loras: loras
    vae: vae
    embeddings: embeddings
    upscale_models: upscale_models
    clip: clip
    ipadapter: ipadapter
# END AI_STUDIO_MANAGED"""

if not config_path.exists():
    config_path.write_text(block + "\n", encoding="utf-8")
    print("created")
    raise SystemExit(0)

text = config_path.read_text(encoding="utf-8")
if "BEGIN AI_STUDIO_MANAGED" not in text:
    print("user_managed")
    raise SystemExit(0)

pattern = r"# BEGIN AI_STUDIO_MANAGED.*?# END AI_STUDIO_MANAGED"
new_text = re.sub(pattern, block.strip(), text, count=1, flags=re.DOTALL)
if new_text == text:
    print("unchanged")
else:
    config_path.write_text(new_text, encoding="utf-8")
    print("updated")
PY
)"

  case "${action}" in
    created)
      log "Created AI Studio-managed extra_model_paths.yaml"
      ;;
    updated)
      log "Updated AI Studio-managed block in extra_model_paths.yaml"
      ;;
    unchanged)
      log "AI Studio-managed extra_model_paths.yaml already current"
      ;;
    user_managed)
      die "extra_model_paths.yaml exists without AI Studio markers. Merge the ai_studio_drive block manually or rename your file before re-running. The installer will not overwrite unrelated user configuration."
      ;;
    *)
      die "Unexpected extra model paths action: ${action}"
      ;;
  esac

  log "Inspect configuration with: cat ${EXTRA_MODEL_PATHS_FILE}"
}

install_comfyui_repo() {
  phase "Install or update ComfyUI repository"

  if [[ "${FORCE_REINSTALL}" == "1" ]]; then
    if [[ -e "${COMFYUI_DIR}" || -L "${COMFYUI_DIR}" ]]; then
      log "Force reinstall requested — removing ${COMFYUI_DIR}"
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

  if [[ -e "${COMFYUI_DIR}" || -L "${COMFYUI_DIR}" ]]; then
    die "Path exists but is not a ComfyUI git repo: ${COMFYUI_DIR}. Use --force-reinstall --execute to replace."
  fi

  run_step git clone --depth 1 "${COMFYUI_REPO}" "${COMFYUI_DIR}"
}

install_python_requirements() {
  phase "Install Python requirements"
  local requirements="${COMFYUI_DIR}/requirements.txt"

  if [[ ! -f "${requirements}" ]]; then
    if [[ "${EXECUTE}" == "1" ]]; then
      die "requirements.txt not found: ${requirements} (ComfyUI clone may have failed)"
    fi
    log "DRY-RUN: requirements path not present yet (${requirements})"
    return 0
  fi

  log "requirements.txt OK: ${requirements}"
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
      --force-replace-models)
        log "WARN: --force-replace-models is deprecated and ignored. Native ComfyUI models/ is preserved; Drive models use extra_model_paths.yaml."
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

  phase "ComfyUI install/validation"
  if [[ "${EXECUTE}" == "1" ]]; then
    log "mode=execute"
  else
    log "mode=dry-run"
  fi
  log "COMFYUI_DIR=${COMFYUI_DIR}"
  log "SHARED_MODELS=${SHARED_MODELS}"
  log "AI_STUDIO_ROOT=${AI_STUDIO_ROOT}"
  log "EXTRA_MODEL_PATHS_FILE=${EXTRA_MODEL_PATHS_FILE}"

  validate_tools
  validate_drive_layout
  describe_comfyui_state
  install_comfyui_repo
  install_python_requirements
  manage_extra_model_paths

  phase "Complete"
  log "ComfyUI install/validation complete"
  log "Runtime: ${COMFYUI_DIR}"
  log "Native models: ${COMFYUI_DIR}/models (preserved)"
  log "Drive models:  ${SHARED_MODELS} via ${EXTRA_MODEL_PATHS_FILE}"
  log "Next: install or validate custom nodes via install_nodes.py"
}

main "$@"
