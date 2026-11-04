# Security policy

## Intended environment

Forge currently targets a trusted developer using a local machine. It has no multi-user authentication or OS execution sandbox. Keep backend/frontend services on loopback. A GitHub source publication does not make the application suitable for Internet hosting.

Agent edits are proposed in disposable workspaces, checked and approved before application. Filesystem policies, role permissions, command guards and optimistic hashes reduce specific risks; they do not isolate approved project code from the host. Tests, hooks and human terminals can execute local code.

Remote model providers receive bounded source/context. Known-secret redaction is not complete data-loss prevention. Choose providers according to the confidentiality of the source you open.

## Reporting a vulnerability

Do not put credentials, exploit payloads containing private data, application databases or private project source in public issues. Use GitHub private vulnerability reporting if it is enabled for the repository. Otherwise contact the maintainer privately through an established channel before sharing sensitive details. No dedicated security email or response-time guarantee is currently advertised.

Include the affected revision, reproduction steps using synthetic data, impact, platform, and relevant redacted output. Do not test against unrelated repositories or other users' systems.

## Supported versions and credentials

There is no published security-maintenance matrix yet. Report issues against the latest available source and identify the tested revision. Dependency auditing and static scanning are evidence, not a comprehensive security certification.

Never commit real `.env` files, provider keys, GitHub tokens, passwords, private keys, private snapshots or local databases. Use local Git credential helpers for private repositories; Forge has no password/token entry field. If a credential reaches a remote or a shared log, revoke/rotate it through its provider and inspect the full affected history. Removing a current file does not remove historical exposure.
