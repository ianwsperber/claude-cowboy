#!/bin/bash
#
# create-claude-user.sh
# Creates a restricted macOS user account for running Claude Code with limited permissions.
# Idempotent: safe to run multiple times, will update permissions without recreating user.
#
# Usage:
#   sudo ./create-claude-user.sh [OPTIONS]
#
# Options:
#   --write <dir>    Grant read+write access to directory (can be specified multiple times)
#   --read <dir>     Grant read-only access to directory (can be specified multiple times)
#   --copy-config    Copy Claude config from current user's ~/.claude
#   --password       Prompt for password interactively (default: generate random)
#   --help           Show this help message

set -e

USERNAME="claude"
USER_SHELL="/bin/zsh"
HOME_DIR="/Users/$USERNAME"
MIN_UID=550

# Arrays to store directories
WRITE_DIRS=()
READ_DIRS=()
PROMPT_PASSWORD=false
COPY_CONFIG=false

# Global variable to track detected PATH for shell profile
DETECTED_PATH_PREFIX=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_help() {
    head -15 "$0" | tail -13 | sed 's/^# \?//'
    exit 0
}

# Resolve path, handling ~ expansion for the calling user
resolve_path() {
    local path="$1"
    # If path starts with ~, expand it relative to SUDO_USER's home
    if [[ "$path" == "~"* ]]; then
        if [[ -n "$SUDO_USER" ]]; then
            local user_home
            user_home=$(dscl . -read /Users/"$SUDO_USER" NFSHomeDirectory | awk '{print $2}')
            path="${path/#\~/$user_home}"
        fi
    fi
    # Convert to absolute path
    echo "$(cd "$(dirname "$path")" 2>/dev/null && pwd)/$(basename "$path")"
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --write)
                if [[ -z "$2" || "$2" == --* ]]; then
                    log_error "--write requires a directory argument"
                    exit 1
                fi
                WRITE_DIRS+=("$(resolve_path "$2")")
                shift 2
                ;;
            --read)
                if [[ -z "$2" || "$2" == --* ]]; then
                    log_error "--read requires a directory argument"
                    exit 1
                fi
                READ_DIRS+=("$(resolve_path "$2")")
                shift 2
                ;;
            --password)
                PROMPT_PASSWORD=true
                shift
                ;;
            --copy-config)
                COPY_CONFIG=true
                shift
                ;;
            --help|-h)
                show_help
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                ;;
        esac
    done
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

# Check if running on macOS
check_macos() {
    if [[ "$(uname)" != "Darwin" ]]; then
        log_error "This script only works on macOS"
        exit 1
    fi
}

# Check if user exists
user_exists() {
    dscl . -read /Users/"$USERNAME" &>/dev/null
}

# Find next available UID
find_next_uid() {
    local uid=$MIN_UID
    while dscl . -list /Users UniqueID | awk '{print $2}' | grep -q "^${uid}$"; do
        ((uid++))
    done
    echo "$uid"
}

# Generate a secure random password
generate_password() {
    # Generate 24-character password with mixed case, numbers, and symbols
    LC_ALL=C tr -dc 'A-Za-z0-9!@#$%^&*' < /dev/urandom | head -c 24
}

# Create the user account
create_user() {
    if user_exists; then
        log_info "User '$USERNAME' already exists, skipping creation"
        return 0
    fi

    log_info "Creating user '$USERNAME'..."

    local uid
    uid=$(find_next_uid)
    log_info "Using UID: $uid"

    # Get password
    local password
    if [[ "$PROMPT_PASSWORD" == true ]]; then
        echo -n "Enter password for $USERNAME: "
        read -rs password
        echo
        echo -n "Confirm password: "
        read -rs password_confirm
        echo
        if [[ "$password" != "$password_confirm" ]]; then
            log_error "Passwords do not match"
            exit 1
        fi
    else
        password=$(generate_password)
        echo ""
        log_info "Generated password for '$USERNAME':"
        echo -e "${YELLOW}$password${NC}"
        echo ""
        log_warn "Save this password! It will not be shown again."
        log_info "You can change it later with: sudo dscl . -passwd /Users/$USERNAME"
        log_info "Typical usage is via 'sudo -u $USERNAME <command>' which doesn't require the password."
        echo ""
    fi

    # Create user record
    dscl . -create /Users/"$USERNAME"
    dscl . -create /Users/"$USERNAME" UserShell "$USER_SHELL"
    dscl . -create /Users/"$USERNAME" RealName "Claude"
    dscl . -create /Users/"$USERNAME" UniqueID "$uid"
    dscl . -create /Users/"$USERNAME" PrimaryGroupID 20  # staff group
    dscl . -create /Users/"$USERNAME" NFSHomeDirectory "$HOME_DIR"

    # Set password
    dscl . -passwd /Users/"$USERNAME" "$password"

    log_info "User '$USERNAME' created successfully"
}

# Create home directory
setup_home_directory() {
    if [[ -d "$HOME_DIR" ]]; then
        log_info "Home directory already exists"
    else
        log_info "Creating home directory..."
        createhomedir -c -u "$USERNAME" 2>/dev/null || {
            # Fallback if createhomedir fails
            mkdir -p "$HOME_DIR"
            chown "$USERNAME":staff "$HOME_DIR"
            chmod 755 "$HOME_DIR"
        }
    fi

    # Ensure proper ownership
    chown "$USERNAME":staff "$HOME_DIR"
}

# Create keychain for the user (needed for credential storage)
setup_keychain() {
    local keychain_dir="$HOME_DIR/Library/Keychains"
    local keychain_path="$keychain_dir/login.keychain-db"

    if [[ -f "$keychain_path" ]]; then
        log_info "Keychain already exists"
        return 0
    fi

    log_info "Creating keychain for '$USERNAME'..."

    # Create Library/Keychains directory
    mkdir -p "$keychain_dir"
    chown -R "$USERNAME":staff "$HOME_DIR/Library"

    # Generate a random password for the keychain (or use user's password if set)
    local keychain_pass
    keychain_pass=$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32)

    # Create the keychain as the claude user
    sudo -u "$USERNAME" security create-keychain -p "$keychain_pass" login.keychain-db 2>/dev/null || {
        log_warn "Could not create keychain automatically"
        return 0
    }

    # Set it as the default keychain for the user
    sudo -u "$USERNAME" security default-keychain -s login.keychain-db 2>/dev/null || true

    # Unlock it (it will lock when the session ends, but that's fine)
    sudo -u "$USERNAME" security unlock-keychain -p "$keychain_pass" login.keychain-db 2>/dev/null || true

    # Set keychain settings (no auto-lock timeout)
    sudo -u "$USERNAME" security set-keychain-settings login.keychain-db 2>/dev/null || true

    log_info "Keychain created successfully"
}

# Remove existing ACL entries for claude user from a directory
remove_acl_entries() {
    local dir="$1"
    if [[ ! -e "$dir" ]]; then
        return 0
    fi

    # Keep removing ACL entries until none remain (max 20 iterations for safety)
    local max_iterations=20
    local iteration=0

    while ls -le "$dir" 2>/dev/null | grep -q "user:$USERNAME" && [[ $iteration -lt $max_iterations ]]; do
        # Find the index of the first claude ACL entry
        local index
        index=$(ls -le "$dir" 2>/dev/null | grep -n "user:$USERNAME" | head -1 | cut -d: -f1)
        if [[ -n "$index" ]]; then
            # ACL indices in ls -le output start at line after the permissions line
            # We need to subtract 2 (1 for header offset, 1 for 0-indexing)
            local acl_index=$((index - 2))
            chmod -a# "$acl_index" "$dir" 2>/dev/null || break
        fi
        ((iteration++))
    done
}

# Grant ACL permissions to a directory
grant_permissions() {
    local dir="$1"
    local access_type="$2"  # "read" or "write"

    if [[ ! -e "$dir" ]]; then
        log_warn "Directory does not exist: $dir"
        return 1
    fi

    log_info "Setting $access_type access for: $dir"

    # Remove existing ACL entries for this user (idempotent)
    remove_acl_entries "$dir"

    # Add new ACL entry
    if [[ "$access_type" == "write" ]]; then
        # Full read/write/execute with inheritance for subdirectories
        chmod +a "user:$USERNAME allow read,write,execute,delete,append,readattr,writeattr,readextattr,writeextattr,readsecurity,list,search,add_file,add_subdirectory,delete_child,file_inherit,directory_inherit" "$dir"
    else
        # Read-only access with inheritance
        chmod +a "user:$USERNAME allow read,execute,readattr,readextattr,readsecurity,list,search,file_inherit,directory_inherit" "$dir"
    fi
}

# Ensure user is not in admin group and cannot sudo
harden_security() {
    log_info "Applying security hardening..."

    # Remove from admin group if present
    if dseditgroup -o checkmember -m "$USERNAME" admin &>/dev/null; then
        log_info "Removing '$USERNAME' from admin group..."
        dseditgroup -o edit -d "$USERNAME" admin 2>/dev/null || true
    fi

    # User won't have sudo access by default since they're not admin
    # and we haven't added them to sudoers
    log_info "Security hardening complete"
}

# Allow passwordless sudo to the claude user from the calling user
setup_passwordless_sudo() {
    if [[ -z "$SUDO_USER" ]]; then
        log_warn "Cannot determine calling user (SUDO_USER not set). Skipping sudoers setup."
        return 0
    fi

    local sudoers_file="/etc/sudoers.d/claude-user"
    local sudoers_rule="$SUDO_USER ALL=($USERNAME) NOPASSWD: ALL"

    # Check if rule already exists
    if [[ -f "$sudoers_file" ]] && grep -qF "$sudoers_rule" "$sudoers_file" 2>/dev/null; then
        log_info "Passwordless sudo already configured for '$SUDO_USER' -> '$USERNAME'"
        return 0
    fi

    log_info "Configuring passwordless sudo: '$SUDO_USER' -> '$USERNAME'..."

    # Write the sudoers rule
    echo "$sudoers_rule" > "$sudoers_file"
    chmod 440 "$sudoers_file"

    # Validate the sudoers file
    if visudo -c -f "$sudoers_file" &>/dev/null; then
        log_info "Sudoers rule installed successfully"
    else
        log_error "Invalid sudoers rule, removing..."
        rm -f "$sudoers_file"
        return 1
    fi
}

# Grant calling user read access to claude's .claude directory (for dashboard)
setup_claude_data_access() {
    if [[ -z "$SUDO_USER" ]]; then
        return 0
    fi

    local claude_data_dir="$HOME_DIR/.claude"

    # Create the directory if it doesn't exist
    if [[ ! -d "$claude_data_dir" ]]; then
        mkdir -p "$claude_data_dir"
        chown "$USERNAME":staff "$claude_data_dir"
    fi

    log_info "Granting '$SUDO_USER' read access to $claude_data_dir..."

    # Grant read access to the calling user so they can read session data
    chmod +a "user:$SUDO_USER allow read,execute,readattr,readextattr,readsecurity,list,search,file_inherit,directory_inherit" "$claude_data_dir" 2>/dev/null || true
}

# Detect claude installation and grant necessary permissions
setup_claude_access() {
    log_info "Detecting Claude Code installation..."

    # Find claude binary
    local claude_path
    claude_path=$(which claude 2>/dev/null) || {
        log_warn "Claude Code not found in PATH. Skipping automatic setup."
        log_warn "You may need to manually grant read access to the claude installation directory."
        return 0
    }

    log_info "Found claude at: $claude_path"

    # Resolve symlinks to find actual installation
    local claude_real
    claude_real=$(readlink -f "$claude_path" 2>/dev/null || python3 -c "import os; print(os.path.realpath('$claude_path'))")
    log_info "Resolved to: $claude_real"

    # Determine the installation prefix (e.g., /opt/homebrew or /usr/local)
    local install_prefix=""
    if [[ "$claude_real" == /opt/homebrew/* ]]; then
        install_prefix="/opt/homebrew"
    elif [[ "$claude_real" == /usr/local/* ]]; then
        install_prefix="/usr/local"
    elif [[ "$claude_path" == /opt/homebrew/* ]]; then
        install_prefix="/opt/homebrew"
    elif [[ "$claude_path" == /usr/local/* ]]; then
        install_prefix="/usr/local"
    fi

    if [[ -n "$install_prefix" ]]; then
        log_info "Detected installation prefix: $install_prefix"
        grant_permissions "$install_prefix" "read"
        DETECTED_PATH_PREFIX="$install_prefix/bin"
    else
        # Grant access to the specific directories
        local claude_dir
        claude_dir=$(dirname "$claude_real")
        log_info "Granting read access to: $claude_dir"
        grant_permissions "$claude_dir" "read"

        # Also grant access to the bin directory containing the symlink
        local bin_dir
        bin_dir=$(dirname "$claude_path")
        if [[ "$bin_dir" != "$claude_dir" ]]; then
            log_info "Granting read access to: $bin_dir"
            grant_permissions "$bin_dir" "read"
        fi
        DETECTED_PATH_PREFIX="$bin_dir"
    fi

    # Find and grant access to node (claude depends on it)
    local node_path
    node_path=$(which node 2>/dev/null) || true
    if [[ -n "$node_path" && -z "$install_prefix" ]]; then
        local node_real
        node_real=$(readlink -f "$node_path" 2>/dev/null || python3 -c "import os; print(os.path.realpath('$node_path'))")
        local node_dir
        node_dir=$(dirname "$node_real")
        if [[ "$node_dir" != "$claude_dir" ]]; then
            log_info "Granting read access to node: $node_dir"
            grant_permissions "$node_dir" "read"
        fi
    fi
}

# Set up shell profile with correct PATH
setup_shell_profile() {
    local zshrc="$HOME_DIR/.zshrc"

    log_info "Setting up shell profile..."

    # Build PATH additions
    local path_additions=""
    if [[ -n "$DETECTED_PATH_PREFIX" ]]; then
        path_additions="$DETECTED_PATH_PREFIX"
    fi

    # Create or update .zshrc
    local zshrc_content="# Claude user shell configuration
# Auto-generated by create-claude-user.sh

# Add necessary paths for Claude Code
"
    if [[ -n "$path_additions" ]]; then
        zshrc_content+="export PATH=\"$path_additions:\$PATH\"
"
    fi

    zshrc_content+="
# Minimal environment
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# Disable zsh autocorrect (prevents 'correct claude to .claude?' prompts)
unsetopt correct
unsetopt correctall
"

    echo "$zshrc_content" > "$zshrc"
    chown "$USERNAME":staff "$zshrc"
    chmod 644 "$zshrc"

    log_info "Created $zshrc with PATH: $path_additions"
}

# Copy Claude config from source user
copy_claude_config() {
    if [[ "$COPY_CONFIG" != true ]]; then
        return 0
    fi

    if [[ -z "$SUDO_USER" ]]; then
        log_warn "Cannot determine source user (SUDO_USER not set). Skipping config copy."
        return 0
    fi

    local source_home
    source_home=$(dscl . -read /Users/"$SUDO_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')
    local source_claude="$source_home/.claude"
    local dest_claude="$HOME_DIR/.claude"

    if [[ ! -d "$source_claude" ]]; then
        log_warn "Source config directory not found: $source_claude"
        return 0
    fi

    log_info "Copying Claude config from $source_claude..."

    # Create destination directory
    mkdir -p "$dest_claude"

    # Files/directories to copy (essential config only)
    local config_items=(
        "settings.json"
        "commands"
        "plugins"
        "statsig"
    )

    for item in "${config_items[@]}"; do
        if [[ -e "$source_claude/$item" ]]; then
            log_info "  Copying $item..."
            if [[ -L "$source_claude/$item" ]]; then
                # It's a symlink - copy the target, not the link
                cp -RL "$source_claude/$item" "$dest_claude/" 2>/dev/null || true
            elif [[ -d "$source_claude/$item" ]]; then
                cp -R "$source_claude/$item" "$dest_claude/" 2>/dev/null || true
            else
                cp "$source_claude/$item" "$dest_claude/" 2>/dev/null || true
            fi
        fi
    done

    # Fix ownership
    chown -R "$USERNAME":staff "$dest_claude"

    log_info "Config copied successfully"
    log_warn "Note: You may need to re-authenticate Claude Code on first run"
}

# Main execution
main() {
    parse_args "$@"
    check_root
    check_macos

    echo ""
    log_info "=== Claude User Setup ==="
    echo ""

    create_user
    setup_home_directory
    setup_keychain
    harden_security
    setup_passwordless_sudo
    setup_claude_data_access

    echo ""
    log_info "=== Configuring Claude Code Access ==="
    echo ""

    setup_claude_access
    setup_shell_profile
    copy_claude_config

    # Apply additional directory permissions
    if [[ ${#WRITE_DIRS[@]} -gt 0 || ${#READ_DIRS[@]} -gt 0 ]]; then
        echo ""
        log_info "=== Configuring Additional Directory Permissions ==="
        echo ""
    fi

    for dir in "${WRITE_DIRS[@]}"; do
        grant_permissions "$dir" "write"
    done

    for dir in "${READ_DIRS[@]}"; do
        grant_permissions "$dir" "read"
    done

    echo ""
    log_info "=== Setup Complete ==="
    echo ""
    log_info "To run Claude Code as '$USERNAME':"
    echo "  sudo -u $USERNAME -i claude"
    echo ""
    log_info "Or with explicit environment:"
    echo "  sudo -u $USERNAME claude"
    echo ""
}

main "$@"
