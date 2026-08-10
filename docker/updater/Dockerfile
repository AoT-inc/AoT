# AoT updater sidecar.
#
# Small on purpose. This is the one container in the stack that holds the
# Docker socket, so it contains a shell, the Docker CLI, compose, curl -- and
# nothing else. It runs docker/updater/aot_docker_update.sh, which only ever
# pulls the hardcoded AoT image repository.
#
# Not published to GHCR: it is built locally by the compose overlay, so nobody
# ends up running a privileged image they did not build.
FROM docker:28-cli

# curl for the /health gate. Everything else the script needs (sh, sed, awk,
# grep, tr, date) is busybox, already in the base image.
RUN apk add --no-cache curl

# Compose v2 as a CLI plugin. Copied from the official compose binary image
# rather than assumed to be present: the docker:*-cli images have shipped with
# and without the plugin across versions, and "docker compose: not found" would
# only surface mid-update.
COPY --from=docker/compose-bin:v2.29.7 /docker-compose \
     /usr/local/libexec/docker/cli-plugins/docker-compose

# Build context is this directory, not the repo root: the root .dockerignore is
# a whitelist that (correctly) excludes docker/, and the updater needs nothing
# from the application tree anyway.
COPY aot_docker_update.sh /usr/local/bin/aot_docker_update.sh
RUN chmod +x /usr/local/bin/aot_docker_update.sh

ENTRYPOINT ["/usr/local/bin/aot_docker_update.sh"]
CMD ["--loop"]
