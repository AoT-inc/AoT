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

# -k lg : config/__init__.py (and others) wrap strings with the alias `lg = lazy_gettext`.
"${INSTALL_DIRECTORY}"/env/bin/pybabel extract "${INFO_ARGS[@]}" -s -F babel.cfg -k _ -k gettext -k ngettext -k lazy_gettext -k lg -o aot_flask/translations/messages.pot .

# The built-in Integrated Environment Control ships under custom_functions/ (which
# babel.cfg ignores). Extract its FUNCTION_INFORMATION separately and merge so its
# options/descriptions are translatable. Rooting at the dir avoids the ignore.
printf "\n#### Extracting + merging Integrated Environment Control\n"
IEC_CFG=$(mktemp)
printf '[python: **.py]\n' > "${IEC_CFG}"
"${INSTALL_DIRECTORY}"/env/bin/pybabel extract -F "${IEC_CFG}" -k _ -k gettext -k ngettext -k lazy_gettext -k lg \
  -o /tmp/aot_iec.pot functions/custom_functions/env_coordinator_impl/
"${INSTALL_DIRECTORY}"/env/bin/python3 - <<'PYMERGE'
import polib
main = polib.pofile('aot_flask/translations/messages.pot')
iec = polib.pofile('/tmp/aot_iec.pot')
have = {e.msgid for e in main}
for e in iec:
    if e.msgid and e.msgid not in have:
        main.append(e); have.add(e.msgid)
main.save('aot_flask/translations/messages.pot')
PYMERGE
rm -f "${IEC_CFG}" /tmp/aot_iec.pot

printf "\n#### Generating translations\n"

"${INSTALL_DIRECTORY}"/env/bin/pybabel update --ignore-obsolete --update-header-comment -i aot_flask/translations/messages.pot -d aot_flask/translations

# `pybabel update`'s fuzzy-matching can silently borrow msgstr from an
# unrelated similar-looking entry and flag it fuzzy -- fuzzy entries are
# dropped from the compiled .mo (see check_i18n_fuzzy.py), which is how
# previously-working translations have gone missing after unrelated regens.
# Surface it every time instead of finding out in production.
printf "\n#### Checking for extraction blind spots and fuzzy-matched translations\n"
"${INSTALL_DIRECTORY}"/env/bin/python3 "${INSTALL_DIRECTORY}"/aot/scripts/check_i18n_extraction.py
"${INSTALL_DIRECTORY}"/env/bin/python3 "${INSTALL_DIRECTORY}"/aot/scripts/check_i18n_fuzzy.py
printf "^ review any findings above before compiling (pybabel compile) or committing.\n"
