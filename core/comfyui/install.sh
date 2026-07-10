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
COMFYUI_RUNTIME_STATE=""
COMFYUI_RUNTIME_EVIDENCE=""
COMFYUI_LAST_ARCHIVE_PATH=""
COMFYUI_PARTIAL_MARKER_COUNT=0
COMFYUI_CORE_PARTIAL_MARKER_COUNT=0

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
  --force-reinstall Archive existing COMFYUI_DIR, then clone fresh (only with --execute)

Notes:
  Persistent Drive models are configured via ${EXTRA_MODEL_PATHS_FILE}.
  The native ${COMFYUI_DIR}/models directory is preserved.
  Partial or empty runtime directories may be recovered automatically.
  Unknown runtime directories are never deleted without manual intervention.
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

utc_timestamp() {
  date -u +%Y%m%dT%H%M%SZ
}

allocate_unique_path() {
  local candidate="$1"
  if [[ ! -e "${candidate}" && ! -L "${candidate}" ]]; then
    printf '%s' "${candidate}"
    return 0
  fi
  local suffix=1
  while [[ -e "${candidate}.${suffix}" || -L "${candidate}.${suffix}" ]]; do
    suffix=$((suffix + 1))
  done
  printf '%s' "${candidate}.${suffix}"
}

runtime_directory_has_entries() {
  local dir="$1"
  find "${dir}" -mindepth 1 -print -quit 2>/dev/null | grep -q .
}

collect_partial_comfyui_markers() {
  local dir="$1"
  local marker
  local -a markers=(
    main.py
    requirements.txt
    comfy
    web
    nodes.py
    folder_paths.py
    models
    custom_nodes
    input
    output
    temp
  )
  local -a found=()

  for marker in "${markers[@]}"; do
    if [[ -e "${dir}/${marker}" ]]; then
      found+=("${marker}")
    fi
  done

  if ((${#found[@]} > 0)); then
    local joined=""
    local item
    for item in "${found[@]}"; do
      if [[ -n "${joined}" ]]; then
        joined+=", ${item}"
      else
        joined="${item}"
      fi
    done
    COMFYUI_RUNTIME_EVIDENCE="${joined}"
  else
    COMFYUI_RUNTIME_EVIDENCE=""
  fi

  COMFYUI_PARTIAL_MARKER_COUNT="${#found[@]}"
}

count_core_partial_markers() {
  local dir="$1"
  local count=0
  local marker

  for marker in main.py requirements.txt comfy nodes.py folder_paths.py; do
    if [[ -e "${dir}/${marker}" ]]; then
      count=$((count + 1))
    fi
  done

  COMFYUI_CORE_PARTIAL_MARKER_COUNT="${count}"
}

normalize_git_remote_url() {
  local url="$1"
  url="${url%.git}"
  url="${url%/}"
  case "${url}" in
    git@*:*)
      url="${url#git@}"
      url="${url/:/\/}"
      ;;
    ssh://*)
      url="${url#ssh://}"
      ;;
    https://*)
      url="${url#https://}"
      ;;
    http://*)
      url="${url#http://}"
      ;;
    file://*)
      url="${url#file://}"
      ;;
  esac
  printf '%s' "${url,,}"
}

git_repo_origin_url() {
  local dir="$1"
  git -C "${dir}" remote get-url origin 2>/dev/null || true
}

is_recognized_comfyui_origin() {
  local origin="$1"
  local normalized_origin normalized_expected

  if [[ -z "${origin}" ]]; then
    return 1
  fi

  normalized_origin="$(normalize_git_remote_url "${origin}")"
  normalized_expected="$(normalize_git_remote_url "${COMFYUI_REPO}")"

  if [[ "${normalized_origin}" == "${normalized_expected}" ]]; then
    return 0
  fi

  if [[ "${normalized_origin}" == *comfy-org/comfyui* ]]; then
    return 0
  fi

  return 1
}

has_comfyui_repo_structure() {
  local dir="$1"
  [[ -e "${dir}/comfy" || -f "${dir}/nodes.py" || -f "${dir}/folder_paths.py" ]]
}

classify_comfyui_runtime() {
  local dir="$1"
  local origin

  COMFYUI_RUNTIME_STATE=""
  COMFYUI_RUNTIME_EVIDENCE=""

  if [[ ! -e "${dir}" && ! -L "${dir}" ]]; then
    COMFYUI_RUNTIME_STATE="missing"
    return 0
  fi

  if [[ -L "${dir}" ]]; then
    COMFYUI_RUNTIME_EVIDENCE="symlink -> $(readlink "${dir}" 2>/dev/null || echo unknown)"
    COMFYUI_RUNTIME_STATE="unknown_non_git_directory"
    return 0
  fi

  if [[ ! -d "${dir}" ]]; then
    COMFYUI_RUNTIME_EVIDENCE="non-directory path"
    COMFYUI_RUNTIME_STATE="unknown_non_git_directory"
    return 0
  fi

  if [[ -d "${dir}/.git" ]]; then
    if [[ ! -f "${dir}/main.py" || ! -f "${dir}/requirements.txt" ]]; then
      COMFYUI_RUNTIME_EVIDENCE="git directory missing main.py and/or requirements.txt"
      COMFYUI_RUNTIME_STATE="unknown_non_git_directory"
      return 0
    fi

    origin="$(git_repo_origin_url "${dir}")"
    if [[ -z "${origin}" ]]; then
      COMFYUI_RUNTIME_EVIDENCE="git repository with no origin remote"
      COMFYUI_RUNTIME_STATE="unknown_non_git_directory"
      return 0
    fi

    if ! is_recognized_comfyui_origin "${origin}"; then
      COMFYUI_RUNTIME_EVIDENCE="unrecognized git origin: ${origin}"
      COMFYUI_RUNTIME_STATE="unknown_non_git_directory"
      return 0
    fi

    if ! has_comfyui_repo_structure "${dir}"; then
      COMFYUI_RUNTIME_EVIDENCE="recognized ComfyUI origin (${origin}) but missing distinctive ComfyUI paths (comfy/, nodes.py, folder_paths.py)"
      COMFYUI_RUNTIME_STATE="unknown_non_git_directory"
      return 0
    fi

    COMFYUI_RUNTIME_STATE="valid_git_repo"
    return 0
  fi

  if ! runtime_directory_has_entries "${dir}"; then
    COMFYUI_RUNTIME_STATE="empty_directory"
    return 0
  fi

  collect_partial_comfyui_markers "${dir}"

  if [[ -f "${dir}/main.py" && -f "${dir}/requirements.txt" ]]; then
    COMFYUI_RUNTIME_STATE="partial_comfyui_install"
    return 0
  fi

  count_core_partial_markers "${dir}"

  if (( COMFYUI_PARTIAL_MARKER_COUNT >= 3 && COMFYUI_CORE_PARTIAL_MARKER_COUNT >= 2 )); then
    COMFYUI_RUNTIME_STATE="partial_comfyui_install"
    return 0
  fi

  if (( COMFYUI_PARTIAL_MARKER_COUNT >= 4 )); then
    COMFYUI_RUNTIME_STATE="partial_comfyui_install"
    return 0
  fi

  COMFYUI_RUNTIME_STATE="unknown_non_git_directory"
}

print_directory_inventory() {
  local dir="$1"
  local entry

  log "Directory inventory for ${dir}:"
  if ! runtime_directory_has_entries "${dir}"; then
    log "  (empty directory)"
    return 0
  fi

  while IFS= read -r entry; do
    [[ -n "${entry}" ]] && log "  ${entry}"
  done < <(find "${dir}" -mindepth 1 -maxdepth 2 -printf '%y %P\n' 2>/dev/null | head -n 25)

  if find "${dir}" -mindepth 2 -print -quit 2>/dev/null | grep -q .; then
    log "  ... additional nested entries omitted ..."
  fi
}

refuse_unknown_runtime_directory() {
  log "Automatic recovery refused: runtime directory is not a valid ComfyUI git repository."
  if [[ -n "${COMFYUI_RUNTIME_EVIDENCE}" ]]; then
    log "Classification evidence: ${COMFYUI_RUNTIME_EVIDENCE}"
  fi
  print_directory_inventory "${COMFYUI_DIR}"
  die "Unknown runtime directory at ${COMFYUI_DIR}. Resolve manually or rerun with --force-reinstall --execute to archive and reinstall. Unrecognized git repositories are never pulled. Drive models are never deleted."
}

archive_runtime_directory() {
  local label="$1"
  local reason="$2"
  local parent base archive_base archive_path

  parent="$(dirname "${COMFYUI_DIR}")"
  base="$(basename "${COMFYUI_DIR}")"
  archive_base="${parent}/${base}.${label}.$(utc_timestamp)"
  archive_path="$(allocate_unique_path "${archive_base}")"
  COMFYUI_LAST_ARCHIVE_PATH="${archive_path}"

  log "Recovery: ${reason}"
  log "Recovery: archive destination ${archive_path}"

  if [[ "${EXECUTE}" == "1" ]]; then
    run_step mv "${COMFYUI_DIR}" "${archive_path}"
    log "Recovery: archived ${COMFYUI_DIR} -> ${archive_path}"
  else
    log "DRY-RUN: would archive ${COMFYUI_DIR} -> ${archive_path}"
  fi
}

remove_empty_runtime_directory() {
  if [[ "${EXECUTE}" == "1" ]]; then
    run_step rmdir "${COMFYUI_DIR}"
    log "Recovery: removed empty runtime directory ${COMFYUI_DIR}"
  else
    log "DRY-RUN: would remove empty runtime directory ${COMFYUI_DIR}"
  fi
}

clone_comfyui_repo() {
  if [[ "${EXECUTE}" == "1" ]]; then
    run_step git clone --depth 1 "${COMFYUI_REPO}" "${COMFYUI_DIR}"
    log "Recovery: fresh ComfyUI clone installed at ${COMFYUI_DIR}"
  else
    log "DRY-RUN: would clone ${COMFYUI_REPO} -> ${COMFYUI_DIR}"
  fi
}

inspect_comfyui_runtime() {
  phase "Inspect ComfyUI runtime path"

  classify_comfyui_runtime "${COMFYUI_DIR}"
  log "ComfyUI runtime classification: ${COMFYUI_RUNTIME_STATE}"

  case "${COMFYUI_RUNTIME_STATE}" in
    missing)
      log "Runtime path missing (${COMFYUI_DIR}); fresh clone planned."
      ;;
    valid_git_repo)
      log "Valid ComfyUI git repository detected at ${COMFYUI_DIR}"
      if [[ "${EXECUTE}" == "1" ]]; then
        log "git remote: $(git -C "${COMFYUI_DIR}" remote get-url origin 2>/dev/null || echo unknown)"
        log "git HEAD:   $(git -C "${COMFYUI_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
      fi
      if [[ -n "${COMFYUI_RUNTIME_EVIDENCE}" ]]; then
        log "Note: ${COMFYUI_RUNTIME_EVIDENCE}"
      fi
      ;;
    empty_directory)
      log "Runtime directory exists but is empty; safe automatic recovery planned."
      ;;
    partial_comfyui_install)
      log "Partial or interrupted ComfyUI installation detected."
      log "Partial install markers: ${COMFYUI_RUNTIME_EVIDENCE:-unknown}"
      log "Automatic recovery will archive the partial runtime and clone fresh."
      ;;
    unknown_non_git_directory)
      log "Runtime directory does not match a safe automatic recovery profile."
      if [[ -n "${COMFYUI_RUNTIME_EVIDENCE}" ]]; then
        log "Classification evidence: ${COMFYUI_RUNTIME_EVIDENCE}"
      fi
      ;;
  esac
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
      archive_runtime_directory \
        "archived" \
        "force reinstall requested; existing runtime will be archived (not deleted)"
      clone_comfyui_repo
      log "Recovery: force reinstall complete; Drive models were not modified."
      return 0
    fi
    clone_comfyui_repo
    return 0
  fi

  case "${COMFYUI_RUNTIME_STATE}" in
    missing)
      clone_comfyui_repo
      ;;
    valid_git_repo)
      if [[ "${EXECUTE}" == "1" ]]; then
        log "ComfyUI already cloned at ${COMFYUI_DIR} — pulling latest changes"
        git -C "${COMFYUI_DIR}" pull --ff-only
      else
        log "DRY-RUN: would pull latest changes in ${COMFYUI_DIR}"
      fi
      ;;
    empty_directory)
      remove_empty_runtime_directory
      clone_comfyui_repo
      log "Recovery: empty runtime replaced with fresh ComfyUI clone; Drive models were not modified."
      ;;
    partial_comfyui_install)
      archive_runtime_directory \
        "broken" \
        "partial ComfyUI installation detected (markers: ${COMFYUI_RUNTIME_EVIDENCE:-unknown})"
      clone_comfyui_repo
      log "Recovery: partial runtime archived to ${COMFYUI_LAST_ARCHIVE_PATH}"
      log "Recovery: clean runtime installed at ${COMFYUI_DIR}; Drive models were not modified."
      ;;
    unknown_non_git_directory)
      refuse_unknown_runtime_directory
      ;;
    *)
      die "Unexpected ComfyUI runtime classification: ${COMFYUI_RUNTIME_STATE}"
      ;;
  esac
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
  inspect_comfyui_runtime
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
