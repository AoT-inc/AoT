# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting for this repository: **Security → Report a vulnerability** on https://github.com/AoT-inc/AoT. You will get an acknowledgement, and a fix or a mitigation before any public disclosure.

Useful in a report: the version (shown in the web interface footer and in `aot/config/__init__.py`), whether the install is direct or Docker, and steps to reproduce.

## Supported versions

Only the latest release receives security fixes. Upgrade before reporting if you are behind.

## Scope notes

- AoT controls physical equipment. Anything that lets a state-changing action bypass the user approval gate, the MCP safety gate, or role permissions is in scope.
- Exposure of API keys, model provider keys, or remote access tokens is in scope.
- Third-party libraries are listed in [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md); report issues in them upstream as well.
