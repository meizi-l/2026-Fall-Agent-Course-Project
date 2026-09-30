#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
course_root=$(cd -- "$script_dir/.." && pwd)
local_node_version=${MCPMARK_LOCAL_NODE_VERSION:-"v20.18.3"}
local_node_root=${MCPMARK_LOCAL_NODE_ROOT:-"$course_root/third_party/.local/node20"}
local_node_bin="$local_node_root/bin"
filesystem_server_package=${MCPMARK_FILESYSTEM_SERVER_PACKAGE:-"@modelcontextprotocol/server-filesystem@2025.12.18"}
filesystem_server_root=${MCPMARK_FILESYSTEM_SERVER_ROOT:-"$course_root/third_party/.local/mcp-filesystem-server"}
filesystem_server_js="$filesystem_server_root/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"
postgres_image=${MCPMARK_POSTGRES_DOCKER_IMAGE:-"pgvector/pgvector:0.8.0-pg17-bookworm"}
postgres_container=${MCPMARK_POSTGRES_CONTAINER:-"mcpmark-postgres"}
postgres_user=${POSTGRES_USERNAME:-"postgres"}
postgres_password=${POSTGRES_PASSWORD:-"password"}
postgres_port=${POSTGRES_PORT:-"5432"}
container_runtime_override=${MCPMARK_CONTAINER_RUNTIME:-""}
export PATH="$local_node_bin:/opt/homebrew/bin:/usr/local/bin:/opt/homebrew/opt/node@20/bin:/usr/local/opt/node@20/bin:/opt/homebrew/opt/postgresql@17/bin:/usr/local/opt/postgresql@17/bin:$PATH"
mode="auto"
action="dry-run"

usage() {
  cat <<'USAGE'
Usage: bash third_party/install_mcpmark_system_deps.sh [--auto|--macos|--ubuntu|--local-node|--postgres-docker] [--dry-run|--install|--check]

Optional helper for MCPMark system dependencies.

Default behavior is --auto --dry-run: print the commands students/staff should
run for their platform. Use --install only for supported non-privileged package
manager commands. Ubuntu installs are printed for an administrator/root shell;
this helper does not run privileged Linux package-manager commands.

Use --local-node --install to install the pinned Node.js runtime into
course_project/third_party/.local/node20 without system package managers.
This also installs the pinned filesystem MCP server package under
course_project/third_party/.local/mcp-filesystem-server. It is the recommended
fallback when system Node.js 20 is unavailable.

This helper intentionally does not install Docker Desktop/Engine or Podman.
Install and start a container runtime manually on the host. Use
--postgres-docker --install after Docker or Podman is available to pull and
start the pinned Postgres container image used by MCPMark Postgres tasks.
Set MCPMARK_CONTAINER_RUNTIME=docker or MCPMARK_CONTAINER_RUNTIME=podman to
select a specific runtime when both are installed.
After installation, run:

  bash third_party/check_mcpmark_runtimes.sh all
USAGE
}

detect_mode() {
  case "$(uname -s)" in
    Darwin) printf '%s\n' "macos" ;;
    Linux)
      case "$(linux_distribution_id)" in
        ubuntu) printf '%s\n' "ubuntu" ;;
        almalinux) printf '%s\n' "almalinux" ;;
        *) printf '%s\n' "unsupported-linux" ;;
      esac
      ;;
    *) printf '%s\n' "unknown" ;;
  esac
}

linux_distribution_id() {
  local os_release=${MCPMARK_OS_RELEASE_FILE:-"/etc/os-release"}
  local id
  if [[ ! -r "$os_release" ]]; then
    printf '%s\n' "unknown"
    return 0
  fi
  id=$(sed -n 's/^ID=//p' "$os_release" | head -n 1)
  id=${id#\"}
  id=${id%\"}
  printf '%s\n' "$id"
}

print_unsupported_linux_message() {
  cat >&2 <<'EOF'
Unsupported Linux distribution for automatic system-package setup.

The course installer only prints apt-based system package commands for Ubuntu.
You can still use the portable MCPMark runtime pieces:

  bash third_party/install_mcpmark_system_deps.sh --local-node --install
  bash third_party/install_mcpmark_system_deps.sh --postgres-docker --install

Install PostgreSQL 17 client tools (psql, createdb, and pg_restore) using your
distribution's own package-management mechanism. The final environment must pass:

  bash third_party/check_mcpmark_runtimes.sh all
EOF
}

print_almalinux_message() {
  cat >&2 <<'EOF'
Detected AlmaLinux/course-server environment.

The final course grading server is expected to be AlmaLinux 9.x
(RHEL/CentOS/Fedora compatible) on x86_64. The course installer does not run dnf
or modify system packages on that server; host configuration is teaching-team or
administrator managed.

Portable MCPMark runtime pieces may still be installed by the course scripts:

  bash third_party/install_mcpmark_system_deps.sh --local-node --install
  MCPMARK_CONTAINER_RUNTIME=podman bash third_party/install_mcpmark_system_deps.sh --postgres-docker --install

Install PostgreSQL 17 client tools (psql, createdb, and pg_restore) using the
server's approved package-management process. The final environment must pass:

  bash third_party/check_mcpmark_runtimes.sh all
EOF
}

node_platform() {
  local os
  local arch
  os=$(uname -s)
  arch=$(uname -m)
  case "$os:$arch" in
    Darwin:arm64) printf '%s\n' "darwin-arm64" ;;
    Darwin:x86_64) printf '%s\n' "darwin-x64" ;;
    Linux:aarch64|Linux:arm64) printf '%s\n' "linux-arm64" ;;
    Linux:x86_64|Linux:amd64) printf '%s\n' "linux-x64" ;;
    *)
      echo "Unsupported local Node platform: $os $arch" >&2
      return 2
      ;;
  esac
}

print_macos_commands() {
  cat <<'EOF'
# macOS system dependencies
# Requires Homebrew: https://brew.sh
brew install postgresql@17

# Optional system Node fallback only. The recommended course runtime is:
#   bash third_party/install_mcpmark_system_deps.sh --local-node --install
brew install node@20

# Add these tools to PATH if Homebrew does not do it automatically:
export PATH="/opt/homebrew/opt/node@20/bin:/opt/homebrew/opt/postgresql@17/bin:$PATH"

# Install and start Docker Desktop or Podman manually:
# https://www.docker.com/products/docker-desktop/

# Then verify:
bash third_party/check_mcpmark_runtimes.sh filesystem
bash third_party/check_mcpmark_runtimes.sh postgres
EOF
}

install_macos() {
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required for macOS automatic installs. Install it from https://brew.sh, then rerun this helper." >&2
    return 2
  fi
  if ! brew install postgresql@17; then
    echo "Homebrew install failed. See course_project/third_party/README.md Homebrew permissions troubleshooting." >&2
    return 2
  fi
  cat <<'EOF'
Install Docker Desktop or Podman manually and start it before Postgres tests:
https://www.docker.com/products/docker-desktop/

If psql is still not found, add this to your shell:
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"

For Node.js, prefer the pinned project-local runtime:
bash third_party/install_mcpmark_system_deps.sh --local-node --install
EOF
}

print_ubuntu_commands() {
  cat <<'EOF'
# Ubuntu system dependencies
# These commands install Node.js 20 from NodeSource and PostgreSQL 17 client
# tools from the PostgreSQL Global Development Group (apt.postgresql.org).
# Run these commands as root, through your site administrator, or inside a
# prepared course image/container. The helper intentionally avoids embedding
# a privilege-escalation command because student/staff machines may use
# different user and privilege policies.

apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release

# NodeSource Node.js 20.x
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

# PostgreSQL 17 client tools from apt.postgresql.org
install -d /usr/share/postgresql-common/pgdg
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
  | gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
  > /etc/apt/sources.list.d/pgdg.list
apt-get update
apt-get install -y postgresql-client-17

# Install and start Docker Engine/Desktop or Podman for Linux separately:
# https://docs.docker.com/engine/install/

# Then verify:
bash third_party/check_mcpmark_runtimes.sh filesystem
bash third_party/check_mcpmark_runtimes.sh postgres
EOF
}

install_ubuntu() {
  echo "This helper does not run privileged Ubuntu package-manager commands." >&2
  echo "Run \`bash third_party/install_mcpmark_system_deps.sh --ubuntu --dry-run\` and execute those commands as root, through your administrator, or inside a prepared image." >&2
  return 2
}

print_local_node_commands() {
  local platform
  platform=$(node_platform)
  local archive="node-$local_node_version-$platform.tar.xz"
  local url="https://nodejs.org/dist/$local_node_version/$archive"
  cat <<EOF
# Project-local Node.js runtime for MCPMark filesystem tasks.
# This avoids system package managers by installing under the course project.
NODE_VERSION=$local_node_version
NODE_TARGET=$local_node_root
NODE_ARCHIVE_URL=$url
FILESYSTEM_SERVER_PACKAGE=$filesystem_server_package
FILESYSTEM_SERVER_TARGET=$filesystem_server_root

bash third_party/install_mcpmark_system_deps.sh --local-node --install

# Then verify:
bash third_party/check_mcpmark_runtimes.sh filesystem
EOF
}

install_local_node() {
  local platform
  platform=$(node_platform)
  local archive="node-$local_node_version-$platform.tar.xz"
  local url="https://nodejs.org/dist/$local_node_version/$archive"
  local parent
  parent=$(dirname -- "$local_node_root")

  if [[ -x "$local_node_bin/node" ]]; then
    local existing
    existing=$("$local_node_bin/node" --version)
    if [[ "$existing" == "$local_node_version" ]]; then
      echo "Project-local Node.js is already installed."
      echo "NODE=$local_node_bin/node"
      echo "NPM=$local_node_bin/npm"
      echo "NPX=$local_node_bin/npx"
      install_filesystem_server_package
      return 0
    fi
    echo "Project-local Node.js exists at $local_node_root but reports $existing, expected $local_node_version." >&2
    echo "Move that directory aside before reinstalling." >&2
    return 2
  fi

  if [[ -e "$local_node_root" ]]; then
    echo "Project-local Node.js target exists but does not contain bin/node: $local_node_root" >&2
    echo "Move that directory aside before reinstalling." >&2
    return 2
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to download project-local Node.js." >&2
    return 2
  fi
  if ! command -v tar >/dev/null 2>&1; then
    echo "tar is required to extract project-local Node.js." >&2
    return 2
  fi

  mkdir -p "$parent"
  local temp_dir
  temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/course_node20.XXXXXX")
  local archive_path="$temp_dir/$archive"
  echo "Downloading $url"
  curl -fL "$url" -o "$archive_path"
  tar -xJf "$archive_path" -C "$temp_dir"
  mv "$temp_dir/node-$local_node_version-$platform" "$local_node_root"
  echo "Project-local Node.js installed."
  echo "NODE=$local_node_bin/node"
  echo "NPM=$local_node_bin/npm"
  echo "NPX=$local_node_bin/npx"
  install_filesystem_server_package
}

install_filesystem_server_package() {
  if [[ ! -x "$local_node_bin/npm" ]]; then
    echo "npm is required to install the filesystem MCP server package." >&2
    return 2
  fi
  mkdir -p "$filesystem_server_root"
  echo "Installing $filesystem_server_package into $filesystem_server_root"
  "$local_node_bin/npm" install --prefix "$filesystem_server_root" --no-audit --no-fund "$filesystem_server_package"
  if [[ ! -f "$filesystem_server_js" ]]; then
    echo "filesystem MCP server install did not create expected file: $filesystem_server_js" >&2
    return 2
  fi
  echo "FILESYSTEM_SERVER_JS=$filesystem_server_js"
}

print_postgres_docker_commands() {
  local runtime
  runtime=$(resolve_container_runtime_for_print)
  cat <<EOF
# MCPMark Postgres runtime container.
# Requires Docker or Podman already installed and running.
CONTAINER_RUNTIME=$runtime
POSTGRES_IMAGE=$postgres_image
POSTGRES_CONTAINER=$postgres_container
POSTGRES_USERNAME=$postgres_user
POSTGRES_PASSWORD=$postgres_password
POSTGRES_PORT=$postgres_port

$runtime pull $postgres_image
$runtime run -d \\
  --name $postgres_container \\
  -e POSTGRES_PASSWORD=$postgres_password \\
  -e POSTGRES_USER=$postgres_user \\
  -p $postgres_port:5432 \\
  $postgres_image

# If the container already exists, start it instead:
$runtime start $postgres_container

# Then verify:
bash third_party/check_mcpmark_runtimes.sh postgres
EOF
}

resolve_container_runtime_for_print() {
  if [[ -n "$container_runtime_override" ]]; then
    printf '%s\n' "$container_runtime_override"
    return 0
  fi
  if command -v docker >/dev/null 2>&1; then
    printf '%s\n' "docker"
    return 0
  fi
  if command -v podman >/dev/null 2>&1; then
    printf '%s\n' "podman"
    return 0
  fi
  printf '%s\n' "docker"
}

resolve_container_runtime() {
  local runtime
  if [[ -n "$container_runtime_override" ]]; then
    runtime="$container_runtime_override"
    if [[ "$runtime" != "docker" && "$runtime" != "podman" ]]; then
      echo "MCPMARK_CONTAINER_RUNTIME must be docker or podman, got: $runtime" >&2
      return 2
    fi
    if ! command -v "$runtime" >/dev/null 2>&1; then
      echo "Requested container runtime is not on PATH: $runtime" >&2
      return 2
    fi
    printf '%s\n' "$runtime"
    return 0
  fi
  for runtime in docker podman; do
    if command -v "$runtime" >/dev/null 2>&1; then
      printf '%s\n' "$runtime"
      return 0
    fi
  done
  echo "Docker or Podman CLI is required. Install/start a host container runtime first." >&2
  return 2
}

install_postgres_docker() {
  local runtime
  runtime=$(resolve_container_runtime)
  "$runtime" version >/dev/null
  "$runtime" pull "$postgres_image"
  if "$runtime" ps -a --format '{{.Names}}' | grep -qx "$postgres_container"; then
    "$runtime" start "$postgres_container"
  else
    "$runtime" run -d \
      --name "$postgres_container" \
      -e "POSTGRES_PASSWORD=$postgres_password" \
      -e "POSTGRES_USER=$postgres_user" \
      -p "$postgres_port:5432" \
      "$postgres_image"
  fi
  echo "MCPMark Postgres container is available."
  echo "CONTAINER_RUNTIME=$runtime"
  echo "POSTGRES_IMAGE=$postgres_image"
  echo "POSTGRES_CONTAINER=$postgres_container"
  echo "POSTGRES_USERNAME=$postgres_user"
  echo "POSTGRES_PASSWORD=$postgres_password"
  echo "POSTGRES_PORT=$postgres_port"
}

check_postgres_docker() {
  local runtime
  runtime=$(resolve_container_runtime)
  "$runtime" version >/dev/null
  "$runtime" image inspect "$postgres_image" >/dev/null
  "$runtime" ps --format '{{.Names}}' | grep -qx "$postgres_container"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --auto) mode="auto"; shift ;;
    --macos) mode="macos"; shift ;;
    --ubuntu) mode="ubuntu"; shift ;;
    --local-node) mode="local-node"; shift ;;
    --postgres-docker) mode="postgres-docker"; shift ;;
    --dry-run) action="dry-run"; shift ;;
    --install) action="install"; shift ;;
    --check) action="check"; shift ;;
    --help|-h) usage; exit 0 ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$mode" == "auto" ]]; then
  mode=$(detect_mode)
fi

if [[ "$action" == "check" ]]; then
  if [[ "$mode" == "postgres-docker" ]]; then
    check_postgres_docker
    exit $?
  fi
  bash "$script_dir/check_mcpmark_runtimes.sh" all
  exit $?
fi

case "$mode:$action" in
  macos:dry-run) print_macos_commands ;;
  ubuntu:dry-run) print_ubuntu_commands ;;
  local-node:dry-run) print_local_node_commands ;;
  postgres-docker:dry-run) print_postgres_docker_commands ;;
  macos:install) install_macos ;;
  ubuntu:install) install_ubuntu ;;
  local-node:install) install_local_node ;;
  postgres-docker:install) install_postgres_docker ;;
  unknown:*)
    echo "Unsupported OS. Use --macos or --ubuntu, or install dependencies manually." >&2
    exit 2
    ;;
  almalinux:*)
    print_almalinux_message
    exit 2
    ;;
  unsupported-linux:*)
    print_unsupported_linux_message
    exit 2
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
