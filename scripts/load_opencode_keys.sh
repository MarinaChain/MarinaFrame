# Export up to three OpenCode Go keys for usage-based key rotation.
#
# Usage (source it; do not execute it):
#   source scripts/load_opencode_keys.sh [keys-file]
#
# Default file: ~/.config/marinaframe/opencode-go-keys.txt (mode 600).
# Format: one key per line. Lines that are empty or contain "@" (account
# labels) are skipped. Keys go to OPENCODE_API_KEY, OPENCODE_API_KEY_2 and
# OPENCODE_API_KEY_3 in file order. No key value is printed.

marinaframe_keys_file="${1:-$HOME/.config/marinaframe/opencode-go-keys.txt}"
if [ ! -r "$marinaframe_keys_file" ]; then
    echo "load_opencode_keys: cannot read $marinaframe_keys_file" >&2
    return 1 2>/dev/null || exit 1
fi
if [ -n "$(find "$marinaframe_keys_file" -perm -044 2>/dev/null)" ]; then
    echo "load_opencode_keys: $marinaframe_keys_file is readable by others; run chmod 600" >&2
    return 1 2>/dev/null || exit 1
fi

unset OPENCODE_API_KEY OPENCODE_API_KEY_2 OPENCODE_API_KEY_3
marinaframe_slot=0
while IFS= read -r marinaframe_line || [ -n "$marinaframe_line" ]; do
    marinaframe_line="${marinaframe_line//[[:space:]]/}"
    case "$marinaframe_line" in
        "" | *@*) continue ;;
    esac
    marinaframe_slot=$((marinaframe_slot + 1))
    case "$marinaframe_slot" in
        1) export OPENCODE_API_KEY="$marinaframe_line" ;;
        2) export OPENCODE_API_KEY_2="$marinaframe_line" ;;
        3) export OPENCODE_API_KEY_3="$marinaframe_line" ;;
        *) echo "load_opencode_keys: only three keys are used; extra lines ignored" >&2; break ;;
    esac
done < "$marinaframe_keys_file"

echo "load_opencode_keys: loaded $((marinaframe_slot > 3 ? 3 : marinaframe_slot)) key(s)" >&2
unset marinaframe_keys_file marinaframe_line marinaframe_slot
