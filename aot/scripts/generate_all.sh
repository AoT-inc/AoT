#!/bin/bash
#
# Generates all required AoT files
#
# Includes:
#
# AoT Manual
# API Docs (swager)
# Translations
#
# Requirements (for generate_manual_api.sh):
# sudo apt install npm
# sudo npm install -g redoc-cli
# sudo npm install -g npx

INSTALL_DIRECTORY=$( cd "$( dirname "${BASH_SOURCE[0]}" )/../../" && pwd -P )

"${INSTALL_DIRECTORY}"/env/bin/python "${INSTALL_DIRECTORY}"/aot/scripts/generate_manual_inputs_by_measure.py
"${INSTALL_DIRECTORY}"/env/bin/python "${INSTALL_DIRECTORY}"/aot/scripts/generate_manual_inputs.py
"${INSTALL_DIRECTORY}"/env/bin/python "${INSTALL_DIRECTORY}"/aot/scripts/generate_manual_outputs.py
"${INSTALL_DIRECTORY}"/env/bin/python "${INSTALL_DIRECTORY}"/aot/scripts/generate_manual_actions.py
"${INSTALL_DIRECTORY}"/env/bin/python "${INSTALL_DIRECTORY}"/aot/scripts/generate_manual_functions.py
"${INSTALL_DIRECTORY}"/env/bin/python "${INSTALL_DIRECTORY}"/aot/scripts/generate_manual_geo.py
"${INSTALL_DIRECTORY}"/env/bin/python "${INSTALL_DIRECTORY}"/aot/scripts/generate_manual_notes.py
"${INSTALL_DIRECTORY}"/env/bin/python "${INSTALL_DIRECTORY}"/aot/scripts/generate_manual_widgets.py
/bin/bash "${INSTALL_DIRECTORY}"/aot/scripts/generate_manual_api.sh
/bin/bash "${INSTALL_DIRECTORY}"/aot/scripts/generate_translations_pybabel.sh

# Compile translations, generate .mo binary files
/bin/bash "${INSTALL_DIRECTORY}"/aot/scripts/upgrade_commands.sh compile-translations

# After generating translations, generate translated docs
"${INSTALL_DIRECTORY}"/env/bin/python "${INSTALL_DIRECTORY}"/aot/scripts/generate_doc_translations.py
