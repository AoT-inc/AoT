# Contributing to AoT

Thank you for looking. This page is the short version; the repository's own guard scripts and workflow comments hold the long one.

## Before you start

- Read [ARCHITECTURE.md](ARCHITECTURE.md) once. It is one page.
- Front-end JavaScript sources are not in this repository; only built bundles are. Changes that need JavaScript cannot be made from a clone of this repository. Python, templates, styles, tests, and migrations can.
- Questions and bug reports go to [Issues](https://github.com/AoT-inc/AoT/issues). Security reports go through [SECURITY.md](SECURITY.md), never a public issue.

## Development environment

Docker is the supported development setup:

```bash
docker compose -f docker/docker-compose.yml up -d
```

The application is at `http://127.0.0.1:8084/`. The direct install (`install/setup.sh`) also works on Debian-based Linux, and is the only way to exercise GPIO, I2C, and 1-Wire hardware.

## Tests

```bash
python3 -m pytest aot/tests -q
```

The unit suite runs in about three minutes and needs no database preparation: `aot/tests/conftest.py` builds a fresh schema in a temporary directory, so the repository database is never opened. End-to-end tests run only when `AOT_E2E_BASE_URL` points at a running instance (see `docs/design/e2e-testing.md`).

## Commit hooks

Enable the repository hooks once per clone:

```bash
git config core.hooksPath .githooks
```

They check, among other things, that a new alembic migration also bumps `ALEMBIC_VERSION` in `aot/config/__init__.py`. A migration that does not is never applied and fails silently at run time. CI repeats the check.

They also block new violations of the package dependency directions in `ARCHITECTURE.md` §4 (existing violations are frozen in `aot/scripts/import_layers_baseline.txt`, not re-litigated on every commit). CI repeats this check too.

If a commit changes code linked to a manual section (see *Linking code to the manual* below), the pre-commit hook lists the affected sections but does not block the commit. If the `claude` CLI is installed, the post-commit hook then drafts updates to those sections in English, Korean and Japanese in the background. It leaves the drafts uncommitted so you can review them. A report is written to `.local/manual_sync/last-run.md`. Set `AOT_SKIP_MANUAL_AUTODRAFT=1` to turn this off.

## Conventions

- **Commit messages** follow `type(scope): subject`, for example `fix(geo): …` or `docs: …`. The subject says what was wrong and what changed, not just the file touched.
- **Database changes** need a migration in `alembic_db/alembic/versions/` and the `ALEMBIC_VERSION` bump. New installs build the schema from the models; upgrades run the migration chain.
- **User-facing strings** are wrapped for translation: `_` / `gettext` in templates and routes, `lazy_gettext` (often imported as `lg`) for module-level labels such as custom options. Do not hard-code English or Korean into templates or Python messages.
- **Vocabulary is neutral.** AoT is not tied to one kind of site. Prefer site, zone, area, target over domain-specific words unless the feature is genuinely about that domain.
- **Manual pages** (`docs/*.md`) are English canonical with `.ko.md` and `.ja.md` translations. A translation is all of a page or none of it; a partial translation replaces the whole English page with less.
- **Linking code to the manual.** When code implements something a manual section describes, add a comment naming that section: `# @manual Notices#poll` directly above a function or class (or `@manual …` inside its docstring). A comment anywhere else covers the whole file, and a comment followed later by `@manual-end` covers only the lines in between. Templates, JavaScript and YAML use the same syntax in their own comment style. The linked heading needs an explicit anchor, such as `## Poll { #poll }`, in every language file. `aot/scripts/manual_sync.py` records a fingerprint of the linked code in `docs/.manual-sync.json`. When the code changes, the section is marked out of date until the manual is updated. If the change does not affect the manual, run `python3 aot/scripts/manual_sync.py stamp Notices#poll` to mark it current.
- **Design notes** go in `docs/design/` and are listed in its `README.md`. They are working documents, not manual pages.
- **Changelog** entries go under the Unreleased heading in `CHANGELOG.md`, one line each, in plain words.

## Pull requests

Target `main`. Keep a pull request to one change. The CI workflows in `.github/workflows/` must pass; each one's header comment explains what it guards and why it exists.
