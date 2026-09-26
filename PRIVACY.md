# Privacy Policy

**Effective Date:** September 2026  
**Project:** Clair Obscur: Expedition 33 — Discord Rich Presence (`Expedition33_RPC`)  
**Maintainer:** SolaneHub  

---

## 1. Overview
This Privacy Policy outlines how the **Expedition33_RPC** companion application ("the Software") interacts with your system and Discord. We are committed to complete privacy and transparency.

## 2. Zero Data Collection & Storage
- **No Personal Data Collected**: The Software does **not** collect, store, transmit, or harvest any personal information, credentials, Discord tokens, or player IDs.
- **No External Telemetry or Tracking**: The Software does not include third-party tracking scripts, analytics libraries, or telemetry beacons.
- **100% Local Execution**: All game state detection (reading local save files and UE4SS Lua game thread state) occurs strictly within your local computer's memory and disk.

## 3. Communication with Discord
The Software communicates exclusively with your locally running Discord desktop client via local Inter-Process Communication (IPC pipes: `\\?\pipe\discord-ipc-0`). 
- Only in-game status details (zone name, combat encounter, expedition flag, elapsed session time) are transmitted to Discord to populate your Rich Presence profile card.
- No chat messages, friend lists, or account credentials are accessed or requested.

## 4. GitHub Releases & Update Checks
If auto-update is enabled, the Software queries the public GitHub REST API (`https://api.github.com/repos/SolaneHub/Expedition33_RPC/releases/latest`) solely to compare the local version string against the latest published release tag. No user identifiers or machine fingerprints are transmitted.

## 5. Contact & Questions
For any questions regarding this policy or the software's privacy architecture, please open an issue or inquiry on the official repository:  
[GitHub Repository - SolaneHub/Expedition33_RPC](https://github.com/SolaneHub/Expedition33_RPC)
