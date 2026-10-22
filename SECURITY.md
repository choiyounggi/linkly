# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities privately. Open this repository's **Security** tab and choose **Report a vulnerability**, or go straight to <https://github.com/choiyounggi/linkly/security/advisories/new>. GitHub describes the form in [Privately reporting a security vulnerability](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability).

Do not open a public issue, pull request, or discussion for a suspected vulnerability. A public report discloses the problem before a fix exists.

Include what you can: the affected version or commit, the component (compiler, runtime, CLI, or a plugin), steps to reproduce, and the impact you expect.

## Supported versions

linkly is pre-1.0 and follows the 0.x compatibility policy in [docs/compatibility.md](docs/compatibility.md).

| Version | Supported |
|---------|-----------|
| Latest release | Yes |
| Older 0.x releases | No |

Security fixes are made on `main` and ship in the next release. Older releases do not receive backported fixes; upgrade to the latest release.

## Response timeline

- We acknowledge a vulnerability report within 3 days.
- We aim to release a fix, or to publish a coordinated disclosure, within 90 days of the report.

If a fix needs more time, we tell the reporter before day 90 and agree on a new disclosure date with them.

## Disclosure policy

After a fix is released, the vulnerability is disclosed publicly as a GitHub Security Advisory on this repository. The advisory credits the reporter unless they ask not to be named.
