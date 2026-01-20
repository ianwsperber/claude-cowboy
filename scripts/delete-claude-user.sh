#!/bin/bash
#
# delete-claude-user.sh
# Removes the claude user account and cleans up ACL permissions.
#
# Usage:
#   sudo ./delete-claude-user.sh [OPTIONS]
#
# Options:
#   --keep-home      Keep the home directory (default: prompt to delete)
#   --delete-home    Delete home directory without prompting
#   --help           Show this help message

set -e

USERNAME="claude"
HOME_DIR="/Users/$USERNAME"

KEEP_HOME=false
DELETE_HOME=false

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
    head -14 "$0" | tail -9 | sed 's/^# \?//'
    exit 0
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --keep-home)
                KEEP_HOME=true
                shift
                ;;
            --delete-home)
                DELETE_HOME=true
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

# Find and remove ACL entries for claude user across the filesystem
cleanup_acls() {
    log_info "Searching for ACL entries to clean up..."

    # Common locations to check for ACLs
    local search_paths=(
        "/Users"
        "/opt"
        "/usr/local"
        "/Applications"
    )

    local found_acls=false

    for search_path in "${search_paths[@]}"; do
        if [[ -d "$search_path" ]]; then
            # Find directories with ACLs for claude user
            while IFS= read -r -d '' dir; do
                if ls -le "$dir" 2>/dev/null | grep -q "user:$USERNAME"; then
                    found_acls=true
                    log_info "Removing ACL from: $dir"
                    remove_acl_entries "$dir"
                fi
            done < <(find "$search_path" -maxdepth 3 -type d -print0 2>/dev/null)
        fi
    done

    if [[ "$found_acls" == false ]]; then
        log_info "No ACL entries found for user '$USERNAME'"
    fi
}

# Remove ACL entries for claude user from a specific directory
remove_acl_entries() {
    local dir="$1"
    if [[ ! -e "$dir" ]]; then
        return 0
    fi

    # Keep removing ACL entries until none remain
    local max_iterations=20
    local iteration=0

    while ls -le "$dir" 2>/dev/null | grep -q "user:$USERNAME" && [[ $iteration -lt $max_iterations ]]; do
        # Find the line number of the first claude ACL entry
        local line_info
        line_info=$(ls -le "$dir" 2>/dev/null | grep -n "user:$USERNAME" | head -1)

        if [[ -n "$line_info" ]]; then
            local line_num
            line_num=$(echo "$line_info" | cut -d: -f1)
            # ACL index is line number minus 2 (accounting for header)
            local acl_index=$((line_num - 2))
            chmod -a# "$acl_index" "$dir" 2>/dev/null || break
        fi
        ((iteration++))
    done
}

# Delete the user account
delete_user() {
    if ! user_exists; then
        log_warn "User '$USERNAME' does not exist"
        return 0
    fi

    log_info "Deleting user '$USERNAME'..."
    dscl . -delete /Users/"$USERNAME"
    log_info "User '$USERNAME' deleted successfully"
}

# Remove sudoers rule
cleanup_sudoers() {
    local sudoers_file="/etc/sudoers.d/claude-user"

    if [[ -f "$sudoers_file" ]]; then
        log_info "Removing sudoers rule..."
        rm -f "$sudoers_file"
        log_info "Sudoers rule removed"
    fi
}

# Handle home directory
handle_home_directory() {
    if [[ ! -d "$HOME_DIR" ]]; then
        log_info "Home directory does not exist: $HOME_DIR"
        return 0
    fi

    if [[ "$KEEP_HOME" == true ]]; then
        log_info "Keeping home directory: $HOME_DIR"
        return 0
    fi

    if [[ "$DELETE_HOME" == true ]]; then
        log_info "Deleting home directory: $HOME_DIR"
        rm -rf "$HOME_DIR"
        log_info "Home directory deleted"
        return 0
    fi

    # Prompt user
    echo ""
    echo -n "Delete home directory $HOME_DIR? [y/N] "
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        log_info "Deleting home directory..."
        rm -rf "$HOME_DIR"
        log_info "Home directory deleted"
    else
        log_info "Keeping home directory"
    fi
}

# Main execution
main() {
    parse_args "$@"
    check_root
    check_macos

    echo ""
    log_info "=== Claude User Removal ==="
    echo ""

    if ! user_exists; then
        log_warn "User '$USERNAME' does not exist, nothing to delete"
        cleanup_acls
        echo ""
        log_info "=== Cleanup Complete ==="
        echo ""
        exit 0
    fi

    cleanup_acls
    cleanup_sudoers
    delete_user
    handle_home_directory

    echo ""
    log_info "=== Removal Complete ==="
    echo ""
}

main "$@"
