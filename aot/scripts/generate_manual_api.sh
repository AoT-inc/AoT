#!/bin/bash
# Generates the API offline HTML documentation
#
# Dependencies
# sudo apt install npm
# sudo npm install -g redoc-cli
# sudo npm install -g npx
#

API_SERV_IP="192.168.0.29"

INSTALL_DIRECTORY=$( cd "$( dirname "${BASH_SOURCE[0]}" )/../../" && pwd -P )

cd "${INSTALL_DIRECTORY}" || return

if curl -k -s --head --request GET https://${API_SERV_IP}/api/swagger.json | grep "200 OK" > /dev/null; then
  if [[ $(command -v redoc-cli) ]]
  then
    rm -rf /tmp/swagger.json
    wget --no-check-certificate https://${API_SERV_IP}/api/swagger.json -O /tmp/swagger.json
    npx redoc-cli bundle -o "${INSTALL_DIRECTORY}"/docs/aot-api.html /tmp/swagger.json
    rm -rf /tmp/swagger.json

    # Change title
    sed -i 's/<title>ReDoc documentation<\/title>/<title>AoT API documentation<\/title>/g' "${INSTALL_DIRECTORY}"/docs/aot-api.html

    cp "${INSTALL_DIRECTORY}"/docs/aot-api.html "${INSTALL_DIRECTORY}"/aot/aot_flask/static/manual/aot-api.html
  else
    printf "Cannot find redoc-cli. See the requirements at the top of this file.\n"
  fi
else
  printf "Cannot connect to https://%s/api/swagger.json\n" "$API_SERV_IP"
fi
