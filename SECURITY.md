# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| v1.5.x  | :white_check_mark: |
| < v1.5  | :x:                |

We strongly advise all users to always run the latest release available on [GitHub Releases](https://github.com/SolaneHub/Expedition33_RPC/releases).

---

## Binary Integrity & Antivirus Transparency

All executables published under GitHub Releases undergo rigorous automated verification:
1. **Reproducible GitHub Actions VM**: Binaries are built in isolated Microsoft Azure Windows virtual machines.
2. **Cryptographic Checksums**: Every release publishes a `SHA256SUMS.txt` file containing the SHA-256 hash of the compiled binaries.
3. **Automated VirusTotal Analysis**: Binaries are submitted to VirusTotal and scanned by 70+ security vendors. The permalink to the live VirusTotal scan is attached directly to each release note.
4. **Sigstore Build Provenance**: GitHub Artifact Attestation links every binary artifact to its exact source commit and runner identity.

---

## Reporting a Vulnerability

If you discover a security vulnerability or security-sensitive issue within Expedition33_RPC, please do **NOT** open a public issue.

Instead, please report it privately:
- Through GitHub's [Private Vulnerability Reporting](https://github.com/SolaneHub/Expedition33_RPC/security/advisories/new) feature on the repository.
- Or by contacting the maintainer directly via GitHub profile.

Reports will be acknowledged promptly and investigated as quickly as possible.
