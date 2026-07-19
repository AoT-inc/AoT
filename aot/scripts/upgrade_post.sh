#!/bin/bash
#
#  upgrade_post.sh - Commands to execute after a AoT upgrade
#

exec 2>&1

if [ "$EUID" -ne 0 ]; then
    printf "Must be run as root\n";
    exit
fi

INSTALL_DIRECTORY=$( cd "$( dirname "${BASH_SOURCE[0]}" )/../../" && pwd -P )
INSTALL_CMD="/bin/bash ${INSTALL_DIRECTORY}/aot/scripts/upgrade_commands.sh"

cd "${INSTALL_DIRECTORY}" || exit

rm -f "${INSTALL_DIRECTORY}"/statistics.csv
rm -f "${INSTALL_DIRECTORY}"/statistics.id

# Delete /env if AoT symlink target isn't /opt/AoT
if [ "$(readlink /var/aot-root)" != "/opt/AoT" ] ; then
  printf "\n#### Deleting and regenerating virtual environment ####\n\n"
  rm -rf "${INSTALL_DIRECTORY}"/env
fi

TIMER_START_initialize=$SECONDS
${INSTALL_CMD} initialize
TIMER_TOTAL_initialize=$((SECONDS - TIMER_START_initialize))

TIMER_START_update_swap_size=$SECONDS
${INSTALL_CMD} update-swap-size
TIMER_TOTAL_update_swap_size=$((SECONDS - TIMER_START_update_swap_size))

TIMER_START_update_apt=$SECONDS
${INSTALL_CMD} update-apt
TIMER_TOTAL_update_apt=$((SECONDS - TIMER_START_update_apt))

TIMER_START_update_packages=$SECONDS
${INSTALL_CMD} update-packages
TIMER_TOTAL_update_packages=$((SECONDS - TIMER_START_update_packages))

TIMER_START_web_server_update=$SECONDS
${INSTALL_CMD} web-server-update
TIMER_TOTAL_web_server_update=$((SECONDS - TIMER_START_web_server_update))

TIMER_START_update_logrotate=$SECONDS
${INSTALL_CMD} update-logrotate
TIMER_TOTAL_update_logrotate=$((SECONDS - TIMER_START_update_logrotate))

TIMER_START_setup_virtualenv=$SECONDS
${INSTALL_CMD} setup-virtualenv
TIMER_TOTAL_setup_virtualenv=$((SECONDS - TIMER_START_setup_virtualenv))

TIMER_START_update_pip3=$SECONDS
${INSTALL_CMD} update-pip3
TIMER_TOTAL_update_pip3=$((SECONDS - TIMER_START_update_pip3))

TIMER_START_update_pip3_packages=$SECONDS
${INSTALL_CMD} update-pip3-packages
TIMER_TOTAL_update_pip3_packages=$((SECONDS - TIMER_START_update_pip3_packages))

# Upgrade database
TIMER_START_update_alembic=$SECONDS
${INSTALL_CMD} update-alembic
TIMER_TOTAL_update_alembic=$((SECONDS - TIMER_START_update_alembic))

TIMER_START_update_alembic_post=$SECONDS
${INSTALL_CMD} update-alembic-post
TIMER_TOTAL_update_alembic_post=$((SECONDS - TIMER_START_update_alembic_post))

# Must upgrade database before attempting to access DB with the following script
DB_INFO=$( ${INSTALL_DIRECTORY}/env/bin/python ${INSTALL_DIRECTORY}/aot/scripts/measurement_db.py -i )
INFLUXDB_INSTALLED=$( jq -r  '.influxdb_installed' <<< "${DB_INFO}" )
INFLUXDB_VERSION=$( jq -r  '.influxdb_version' <<< "${DB_INFO}" )

if [ "$INFLUXDB_INSTALLED" == "true" ] && [[ ${INFLUXDB_VERSION} == 1* ]]; then
    TIMER_START_update_influxdb=$SECONDS
    ${INSTALL_CMD} update-influxdb-1
    TIMER_TOTAL_update_influxdb=$((SECONDS - TIMER_START_update_influxdb))
elif [ "$INFLUXDB_INSTALLED" == "true" ] && [[ ${INFLUXDB_VERSION} == 2* ]]; then
    TIMER_START_update_influxdb=$SECONDS
    ${INSTALL_CMD} update-influxdb-2
    TIMER_TOTAL_update_influxdb=$((SECONDS - TIMER_START_update_influxdb))
fi

TIMER_START_update_dependencies=$SECONDS
${INSTALL_CMD} update-dependencies
TIMER_TOTAL_update_dependencies=$((SECONDS - TIMER_START_update_dependencies))

TIMER_START_update_aot_startup_script=$SECONDS
${INSTALL_CMD} update-aot-startup-script
TIMER_TOTAL_update_aot_startup_script=$((SECONDS - TIMER_START_update_aot_startup_script))

TIMER_START_compile_translations=$SECONDS
${INSTALL_CMD} compile-translations
TIMER_TOTAL_compile_translations=$((SECONDS - TIMER_START_compile_translations))

TIMER_START_generate_widget_html=$SECONDS
${INSTALL_CMD} generate-widget-html
TIMER_TOTAL_generate_widget_html=$((SECONDS - TIMER_START_generate_widget_html))

TIMER_START_build_notes_widget=$SECONDS
${INSTALL_CMD} build-notes-widget
TIMER_TOTAL_build_notes_widget=$((SECONDS - TIMER_START_build_notes_widget))

TIMER_START_update_permissions=$SECONDS
${INSTALL_CMD} update-permissions
TIMER_TOTAL_update_permissions=$((SECONDS - TIMER_START_update_permissions))

TIMER_START_restart_daemon=$SECONDS
${INSTALL_CMD} restart-daemon
TIMER_TOTAL_restart_daemon=$((SECONDS - TIMER_START_restart_daemon))

# SSL certificate validation and generation
printf "\n#### Checking SSL certificates...\n"

# Fix nested directory issue from previous buggy upgrades
# (cp -R bug created ssl_certs/ssl_certs/ssl_certs/... on each upgrade)
SSL_BASE="${INSTALL_DIRECTORY}/aot/aot_flask/ssl_certs"
NESTED_CERT_FOUND=false

# Find and move certificates from any nested ssl_certs directories
while [ -d "${SSL_BASE}/ssl_certs" ]; do
    if [ -f "${SSL_BASE}/ssl_certs/server.crt" ] || [ -f "${SSL_BASE}/ssl_certs/server.key" ]; then
        printf "#### Found SSL certificates in nested directory. Moving to correct location...\n"
        mv "${SSL_BASE}"/ssl_certs/server.* "${SSL_BASE}/" 2>/dev/null || true
        NESTED_CERT_FOUND=true
    fi
    # Remove the nested directory (even if empty)
    rmdir "${SSL_BASE}/ssl_certs" 2>/dev/null || rm -rf "${SSL_BASE}/ssl_certs"
done

# Generate certificates if missing
if [ ! -f "${SSL_BASE}/server.crt" ] || [ ! -f "${SSL_BASE}/server.key" ]; then
    printf "#### SSL certificates not found. Generating new certificates...\n"
    TIMER_START_ssl_certs_generate=$SECONDS
    ${INSTALL_CMD} ssl-certs-generate 2>&1 | tee -a /var/log/aot/aotupgrade.log
    TIMER_TOTAL_ssl_certs_generate=$((SECONDS - TIMER_START_ssl_certs_generate))
else
    if [ "$NESTED_CERT_FOUND" = true ]; then
        printf "#### SSL certificates recovered from nested directory.\n"
    else
        printf "#### SSL certificates verified.\n"
    fi
    TIMER_TOTAL_ssl_certs_generate=0
fi


TIMER_START_web_server_restart=$SECONDS
${INSTALL_CMD} web-server-restart
TIMER_TOTAL_web_server_restart=$((SECONDS - TIMER_START_web_server_restart))

TIMER_START_web_server_connect=$SECONDS
${INSTALL_CMD} web-server-connect
TIMER_TOTAL_web_server_connect=$((SECONDS - TIMER_START_web_server_connect))

printf "\nStage 3 execution time summary:"
printf "\ninitialize:                   %s s" "${TIMER_TOTAL_initialize}"
printf "\nupdate-swap-size:             %s s" "${TIMER_TOTAL_update_swap_size}"
printf "\nsetup-virtualenv:             %s s" "${TIMER_TOTAL_setup_virtualenv}"
printf "\nupdate-apt:                   %s s" "${TIMER_TOTAL_update_apt}"
printf "\nupdate-packages:              %s s" "${TIMER_TOTAL_update_packages}"
printf "\nweb-server-update:            %s s" "${TIMER_TOTAL_web_server_update}"
printf "\nupdate-logrotate:             %s s" "${TIMER_TOTAL_update_logrotate}"
printf "\nupdate-pip3:                  %s s" "${TIMER_TOTAL_update_pip3}"
printf "\nupdate-pip3-packages:         %s s" "${TIMER_TOTAL_update_pip3_packages}"
printf "\nupdate-dependencies:          %s s" "${TIMER_TOTAL_update_dependencies}"
printf "\nupdate-influxdb:              %s s" "${TIMER_TOTAL_update_influxdb}"
printf "\nupdate-alembic:               %s s" "${TIMER_TOTAL_update_alembic}"
printf "\nupdate-alembic-post:          %s s" "${TIMER_TOTAL_update_alembic_post}"
printf "\nupdate-aot-startup-script: %s s" "${TIMER_TOTAL_update_aot_startup_script}"
printf "\ncompile-translations:         %s s" "${TIMER_TOTAL_compile_translations}"
printf "\ngenerate-widget-html:         %s s" "${TIMER_TOTAL_generate_widget_html}"
printf "\nbuild-notes-widget:           %s s" "${TIMER_TOTAL_build_notes_widget}"
printf "\nupdate-permissions:           %s s" "${TIMER_TOTAL_update_permissions}"
printf "\nrestart-daemon:               %s s" "${TIMER_TOTAL_restart_daemon}"
printf "\nssl-certs-generate:           %s s" "${TIMER_TOTAL_ssl_certs_generate}"
printf "\nweb-server_restart:           %s s" "${TIMER_TOTAL_web_server_restart}"
printf "\nweb-server-connect:           %s s\n" "${TIMER_TOTAL_web_server_connect}"
