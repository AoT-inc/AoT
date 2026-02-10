import json
import logging
import re
from urllib.request import urlopen
from packaging.version import parse

# Mock config
AOT_VERSION = '26.0.1'
TAGS_URL = 'https://api.github.com/repos/aot-inc/AoT/git/refs/tags'

# Configure logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("aot.github_release_info")

class AoTRelease:
    def __init__(self, tag_uri=TAGS_URL, access_token=None):
        self.aot_tags = []
        self.tag_uri = tag_uri
        self.access_token = access_token
        self.update_aot_tags()

    def update_aot_tags(self):
        """Populate the list of AoT tags."""
        response_tags = []
        parsed_tags = []
        try:
            print(f"Fetching tags from {self.tag_uri}...")
            response = urlopen(self.tag_uri)
            data = response.read().decode("utf-8")
            response_tags = json.loads(data)
            print(f"Found {len(response_tags)} tags.")
            for t in response_tags:
                print(f"Raw Tag: {t.get('ref')}")
        except Exception as err:
            logger.exception(f"Github API Response: {err}")
            print(f"Error fetching tags: {err}")
            return

        for each_tag in response_tags:
            if "ref" in each_tag and "/" in each_tag['ref']:
                tag_full = each_tag['ref'].split('/')
                # Original regex: 'v(\d+)\.(\d+)\.\d+'
                # It enforces 3 parts: major, minor, something (patch?)
                if len(tag_full) == 3 and re.match(r'v(\d+)\.(\d+)\.\d+', tag_full[2]):
                    parsed_tags.append(tag_full[2])
        self.aot_tags = parsed_tags

    def github_releases(self, major_version):
        """Return a reversed list of AoT release versions with a Major revision number"""
        all_versions = []
        try:
            for each_tag in self.aot_tags:
                # Original regex: f'v{major_version}.*(\d\.\d)'
                # This seems slightly loose. Let's test it.
                if re.match(f'v{major_version}.*(\d\.\d)', each_tag):
                    all_versions.append(each_tag[1:])
        except Exception:
            logger.exception("github_releases()")

        return self.sort_reverse_list(all_versions)

    def github_latest_release(self):
        """Return the latest AoT release version."""
        all_versions = []
        try:
            for each_tag in self.aot_tags:
                if each_tag:
                    all_versions.append(each_tag[1:])
        
            if all_versions:
                latest_release = self.sort_reverse_list(all_versions)[0]
                return latest_release
        except Exception:
            logger.exception("github_latest_release()")
        return None

    def github_upgrade_exists(self):
        errors = []
        upgrade_exists = False
        releases = []
        current_latest_tag = None

        if not self.aot_tags:
            errors.append("Could not download latest AoT version information.")
        try:
            current_latest_tag = self.github_latest_release()
            current_maj_version = int(AOT_VERSION.split('.')[0])
            releases = self.github_releases(current_maj_version)

            if releases:
                if (parse(releases[0]) > parse(AOT_VERSION) or
                        (current_latest_tag and parse(current_latest_tag) > parse(AOT_VERSION))):
                    upgrade_exists = True
        except Exception as e:
            logger.exception("github_upgrade_exists()")
            errors.append(f"Error: {e}")
        return upgrade_exists, releases, self.aot_tags, current_latest_tag, errors

    @staticmethod
    def sort_reverse_list(versions_unsorted):
        versions_sorted = []
        try:
            for each_ver in versions_unsorted:
                versions_sorted.append(each_ver)
            versions_sorted.sort(key=lambda s: list(map(int, s.split('.'))))
            versions_sorted.reverse()
        except Exception:
            logger.exception("sort_reverse_list()")
        return versions_sorted

if __name__ == "__main__":
    print(f"Testing with Current Version: {AOT_VERSION}")
    release = AoTRelease()
    upgrade, releases, tags, latest, errors = release.github_upgrade_exists()
    
    print("\nResults:")
    print(f"Upgrade Exists: {upgrade}")
    print(f"Latest Release (all): {latest}")
    print(f"Releases for major version {AOT_VERSION.split('.')[0]}: {releases}")
    print(f"Errors: {errors}")

    # Test hypothetical new version
    print("\n--- TestRegex ---")
    major = 26
    test_tags = ['v26.0.2', 'v26.1.0', 'v26.0.1', 'v27.0.0']
    print(f"Testing regex against: {test_tags}")
    matched = []
    for t in test_tags:
        if re.match(f'v{major}.*(\d\.\d)', t):
             matched.append(t)
    print(f"Matches for major {major}: {matched}")
