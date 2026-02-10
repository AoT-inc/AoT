#!/bin/bash
#
# Generates the AoT translation .po files
#
# Requires: pybabel in virtualenv
#

INSTALL_DIRECTORY=$( cd "$( dirname "${BASH_SOURCE[0]}" )/../../" && pwd -P )
CURRENT_VERSION=$("${INSTALL_DIRECTORY}"/env/bin/python3 "${INSTALL_DIRECTORY}"/aot/utils/github_release_info.py -c 2>&1)

INFO_ARGS=(
  --project "AoT"
  --version "${CURRENT_VERSION}"
  --copyright "Kyle T. Gabriel"
  --msgid-bugs-address "aot@kylegabriel.com"
)

cd "${INSTALL_DIRECTORY}"/aot || return

printf "\n#### Extracting translatable texts\n"

"${INSTALL_DIRECTORY}"/env/bin/pybabel extract "${INFO_ARGS[@]}" -s -F babel.cfg -k _ -k gettext -k ngettext -k lazy_gettext -o aot_flask/translations/messages.pot .

printf "\n#### Generating translations\n"

"${INSTALL_DIRECTORY}"/env/bin/pybabel update --ignore-obsolete --update-header-comment -i aot_flask/translations/messages.pot -d aot_flask/translations
