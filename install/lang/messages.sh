#!/bin/bash
#
#  messages.sh - AoT installer message catalog
#
#  Loads install/lang/<code>.msg files (one "key=value" pair per line) and
#  exposes msg()/pmsg() helpers so setup.sh can show its dialogs and progress
#  output in the language the user selected. "\n" inside a stored value is a
#  literal two-character marker, not a real newline in this file - dialog
#  renders it as a line break on its own, and pmsg() expands it via printf
#  when writing to the terminal/log.
#
#  Usage:
#    source install/lang/messages.sh
#    dialog --title "$(msg license_title)" --yesno "$(msg license_body)" ...
#    pmsg install_begin "${START_B}" | tee -a "${LOG_LOCATION}"
#

_MSG_LANG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
declare -gA MSG=()

# _msg_load_lang <code> - load install/lang/<code>.msg into MSG["<code>:<key>"]
_msg_load_lang() {
    local lang="$1"
    local file="${_MSG_LANG_DIR}/${lang}.msg"
    [[ -f "${file}" ]] || return 1
    local line key value
    while IFS= read -r line || [[ -n "${line}" ]]; do
        [[ -z "${line}" ]] && continue
        key="${line%%=*}"
        value="${line#*=}"
        MSG["${lang}:${key}"]="${value}"
    done < "${file}"
}

# English is the fallback catalog and is always loaded first.
_msg_load_lang "en"
if [[ -n "${LANGUAGE:-}" && "${LANGUAGE}" != "en" ]]; then
    _msg_load_lang "${LANGUAGE}"
fi

# msg <key> - raw localized text for the current $LANGUAGE, falling back to
# English (or the key name itself) if no translation exists. Any literal
# "\n" in the value is left untouched, since dialog interprets it directly.
msg() {
    local key="$1"
    local lang="${LANGUAGE:-en}"
    local val="${MSG["${lang}:${key}"]:-}"
    if [[ -z "${val}" ]]; then
        val="${MSG["en:${key}"]:-${key}}"
    fi
    printf '%s' "${val}"
}

# pmsg <key> [args...] - print a localized message (terminal/log output).
# The looked-up value is used as the printf format string, so any "\n" or
# "%s"/"%d" placeholders it contains are expanded/substituted normally.
pmsg() {
    local key="$1"
    shift
    # shellcheck disable=SC2059
    printf "$(msg "${key}")" "$@"
}
