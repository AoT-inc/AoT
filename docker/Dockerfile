FROM debian:stable-slim

ENV DOCKER_CONTAINER TRUE

RUN useradd -ms /bin/bash pi
RUN useradd -ms /bin/bash aot

COPY ./aot/scripts/upgrade_commands.sh /home/aot/aot/scripts/upgrade_commands.sh

RUN /home/aot/aot/scripts/upgrade_commands.sh docker-create-files-directories-symlinks
RUN /home/aot/aot/scripts/upgrade_commands.sh update-apt
RUN /home/aot/aot/scripts/upgrade_commands.sh update-packages
RUN /home/aot/aot/scripts/upgrade_commands.sh ssl-certs-generate
RUN /home/aot/aot/scripts/upgrade_commands.sh install-docker

COPY ./install/requirements.txt /home/aot/install

RUN /home/aot/aot/scripts/upgrade_commands.sh docker-update-pip
RUN /home/aot/aot/scripts/upgrade_commands.sh docker-update-pip-packages

COPY . /home/aot
WORKDIR /home/aot/aot

RUN /home/aot/aot/scripts/upgrade_commands.sh docker-compile-translations
RUN /home/aot/aot/scripts/upgrade_commands.sh compile-aot-wrapper
