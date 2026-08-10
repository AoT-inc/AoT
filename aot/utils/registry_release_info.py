# -*- coding: utf-8 -*-
"""Release information for Docker installs, read from the container registry.

aot/utils/github_release_info.py answers "what release tags exist in git?",
which is the right question for a bare-metal install (it upgrades by checking
out a tag). A Docker install upgrades by pulling an image, and the image is
published by .github/workflows/docker-publish.yml *after* the tag is pushed --
a multi-arch build takes minutes. During that window the git tag says an
upgrade exists while `docker pull` still 404s, so the Docker upgrade page and
the daemon's upgrade check must ask the registry instead.

Anonymous read against GHCR:

    GET https://ghcr.io/token?service=ghcr.io&scope=repository:aot-inc/aot:pull
    GET https://ghcr.io/v2/aot-inc/aot/tags/list   (Bearer <token>)

This requires the GHCR package to be public (see the prerequisites comment in
docker-publish.yml). If it is private, every call fails closed: no tags, an
error string for the UI, and upgrade_exists() returns False -- never a spurious
"upgrade available".

Read-only. Nothing here pulls, runs or restarts anything.
"""
import json
import logging
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from packaging.version import parse

from aot.config import (AOT_VERSION, DOCKER_IMAGE, DOCKER_REGISTRY_TAGS_URL,
                        DOCKER_REGISTRY_TOKEN_URL)

logger = logging.getLogger("aot.registry_release_info")

# A release tag, and nothing else. docker-publish.yml also pushes the moving
# tags 'latest' and 'YY.MM' plus 'sha-<short>'; none of those identify a
# release, and a moving tag can silently change what it points at.
RELEASE_TAG_RE = re.compile(r'^\d+\.\d+\.\d+$')

# Registry calls happen on the daemon's timer thread and in a page request.
# Neither may hang on an unreachable registry.
REQUEST_TIMEOUT = 10
# tags/list is paginated; follow at most this many pages. AoT publishes a
# handful of tags per release, so this is a runaway guard, not a real limit.
MAX_PAGES = 10


def _sort_reverse(versions):
    """Newest first. Sorts numerically, so 26.08.10 > 26.08.9 (a string sort
    gets that backwards, and the YY.MM scheme guarantees we reach 10)."""
    try:
        return sorted(versions,
                      key=lambda s: [int(part) for part in s.split('.')],
                      reverse=True)
    except Exception:
        logger.exception("_sort_reverse()")
        return list(versions)


class RegistryRelease:
    """Release versions of the AoT image that are actually pullable."""

    def __init__(self, image=DOCKER_IMAGE, token_url=DOCKER_REGISTRY_TOKEN_URL,
                 tags_url=DOCKER_REGISTRY_TAGS_URL):
        self.image = image
        self.token_url = token_url
        self.tags_url = tags_url
        self.image_tags = []     # every tag the registry reports
        self.errors = []
        self.update_image_tags()

    #
    # Registry access
    #

    def _get_token(self):
        """Anonymous pull token. None means we could not authenticate."""
        try:
            with urllib.request.urlopen(
                    self.token_url, timeout=REQUEST_TIMEOUT) as response:
                data = json.loads(response.read().decode('utf-8'))
            # GHCR returns 'token'; some registries return 'access_token'.
            return data.get('token') or data.get('access_token')
        except Exception:
            logger.exception("_get_token()")
            return None

    def _get_json(self, url, token):
        request = urllib.request.Request(url)
        request.add_header('Authorization', f'Bearer {token}')
        request.add_header('Accept', 'application/json')
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            body = json.loads(response.read().decode('utf-8'))
            return body, response.headers.get('Link')

    def update_image_tags(self):
        """Populate self.image_tags from the registry."""
        self.image_tags = []
        self.errors = []

        token = self._get_token()
        if not token:
            self.errors.append(
                "Could not authenticate to the container registry. The image "
                "may be private, or the registry may be unreachable.")
            return

        url = f'{self.tags_url}?n=100'
        tags = []
        try:
            for _page in range(MAX_PAGES):
                body, link = self._get_json(url, token)
                tags.extend(body.get('tags') or [])
                if not link or 'rel="next"' not in link:
                    break
                # Link: </v2/aot-inc/aot/tags/list?n=100&last=x>; rel="next"
                match = re.search(r'<([^>]+)>', link)
                if not match:
                    break
                # The next link is usually host-relative.
                url = urllib.parse.urljoin(self.tags_url, match.group(1))
        except urllib.error.HTTPError as err:
            logger.error(f"Registry tag list HTTP {err.code}")
            self.errors.append(
                f"Could not list image tags (HTTP {err.code}). If this "
                f"persists, check that {self.image} is publicly readable.")
            return
        except (socket.gaierror, urllib.error.URLError):
            logger.error("Cannot reach the container registry")
            self.errors.append(
                "Could not reach the container registry. Check the network "
                "connection.")
            return
        except Exception:
            logger.exception("update_image_tags()")
            self.errors.append("Could not read image tags from the registry.")
            return

        self.image_tags = tags

    #
    # Derived views
    #

    def releases(self, major_version=None):
        """Release versions, newest first. Optionally restricted to one major."""
        versions = [tag for tag in self.image_tags if RELEASE_TAG_RE.match(tag)]
        if major_version is not None:
            versions = [v for v in versions
                        if v.split('.')[0] == str(int(major_version))]
        return _sort_reverse(versions)

    def latest_release(self):
        """Newest pullable release version, or None."""
        all_releases = self.releases()
        return all_releases[0] if all_releases else None

    def tag_exists(self, tag):
        return tag in self.image_tags

    def upgrade_exists(self):
        """Same 5-tuple shape as AoTRelease.github_upgrade_exists(), so the
        daemon, the upgrade page and the MCP tool can use either source.

        :return: (upgrade_exists, releases, all_tags, latest_release, errors)
        """
        errors = list(self.errors)
        upgrade_available = False
        releases = []
        latest = None

        if not self.image_tags and not errors:
            errors.append(
                "The container registry returned no tags for "
                f"{self.image}.")

        try:
            latest = self.latest_release()
            releases = self.releases(int(AOT_VERSION.split('.')[0]))
            if latest and parse(latest) > parse(AOT_VERSION):
                upgrade_available = True
        except Exception:
            logger.exception("upgrade_exists()")
            errors.append(
                "Could not compare the installed version with the versions "
                "published to the container registry.")

        return upgrade_available, releases, self.image_tags, latest, errors
