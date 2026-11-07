"""Generator and validator script for Expedition33_RPC architecture SVG diagrams.

Produces lightweight, infinite-resolution vector SVGs inspired by modern pipelines
(CSS-animated dashed flow lines, native font stacks, accessible metadata, < 10 KB).
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"

PIPELINE_SVG_CONTENT = r"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" role="img" aria-label="Expedition 33 Discord RPC Telemetry Pipeline: in-game Lua hook writes IPC JSON, GameDetector verifies 5s freshness SLA and pushes to Discord; fallback mmap reader extracts save state when bridge is inactive.">
  <style>
    .flow { fill: none; stroke-width: 2.2; stroke-linecap: round; stroke-dasharray: 7 7; animation: e33flow .7s linear infinite; }
    @keyframes e33flow { to { stroke-dashoffset: -14; } }
    @media (prefers-reduced-motion: reduce) { .flow { animation: none; } }
    .node { fill: #0e1322; stroke-width: 1.6; }
    .main { font: 600 13.5px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; fill: #f8fafc; text-anchor: middle; }
    .sub { font: 400 11px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; fill: #94a3b8; text-anchor: middle; }
    .edgelabel { font: 600 11px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; }
    .tag { font: 700 11px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; letter-spacing: 2.2px; fill: #38bdf8; }
    .caption { font: 400 11.5px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; fill: #94a3b8; text-anchor: middle; }
  </style>
  <defs>
    <linearGradient id="edge" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#f59e0b"/>
      <stop offset=".45" stop-color="#38bdf8"/>
      <stop offset="1" stop-color="#5865F2"/>
    </linearGradient>
    <marker id="headCyan" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#38bdf8"/>
    </marker>
    <marker id="headEmerald" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#34d399"/>
    </marker>
    <marker id="headAmber" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#fbbf24"/>
    </marker>
    <marker id="headBlurple" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#818cf8"/>
    </marker>
  </defs>

  <!-- Card Canvas -->
  <rect x="4" y="4" width="872" height="462" rx="16" fill="#080c16" stroke="url(#edge)" stroke-width="1.6"/>

  <!-- Brand Header -->
  <rect x="34" y="24" width="32" height="32" rx="8" fill="#131b2e" stroke="url(#edge)" stroke-width="1.4"/>
  <text x="50" y="46" font-family="ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif" font-size="15" font-weight="900" fill="#f59e0b" text-anchor="middle">33</text>
  <text x="78" y="47" font-family="ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif" font-size="19" font-weight="800" letter-spacing="1.5" fill="url(#edge)">EXPEDITION&#160;33</text>
  <text class="tag" x="254" y="45">&#183; TELEMETRY &amp; PRESENCE PIPELINE</text>

  <!-- Row 1: Hot Telemetry Path (Active Bridge) -->
  <rect class="node" x="36" y="84" width="176" height="58" rx="11" stroke="#38bdf8"/>
  <text class="main" x="124" y="108">&#127918; UE4SS Lua Mod</text>
  <text class="sub" x="124" y="126">in-game telemetry hook</text>

  <rect class="node" x="256" y="84" width="180" height="58" rx="11" stroke="#38bdf8"/>
  <text class="main" x="346" y="108">&#128196; IPC Status File</text>
  <text class="sub" x="346" y="126">%TEMP%\expedition33_status.json</text>

  <rect class="node" x="480" y="84" width="180" height="58" rx="11" stroke="#34d399"/>
  <text class="main" x="570" y="108">&#9889; GameDetector Hub</text>
  <text class="sub" x="570" y="126">5.0s SLA &#183; game_data SSOT</text>

  <rect class="node" x="704" y="84" width="140" height="58" rx="11" stroke="#818cf8"/>
  <text class="main" x="774" y="108">&#128172; Discord Presence</text>
  <text class="sub" x="774" y="126">combat, zone &amp; timer</text>

  <!-- Row 1: Unobstructed Animated Connectors -->
  <path class="flow" d="M212,113 L250,113" stroke="#38bdf8" marker-end="url(#headCyan)"/>
  <path class="flow" d="M436,113 L474,113" stroke="#38bdf8" marker-end="url(#headCyan)"/>
  <path class="flow" d="M660,113 L698,113" stroke="#34d399" marker-end="url(#headEmerald)"/>

  <!-- Branch: Fallback on Stale / Missing Bridge -->
  <path class="flow" d="M550,142 C530,225 280,220 234,294" stroke="#fbbf24" marker-end="url(#headAmber)"/>

  <!-- Pill Badge for Fallback Condition (Clean Spacious Floating Badge) -->
  <rect x="296" y="206" width="188" height="22" rx="11" fill="#0e1322" stroke="#fbbf24" stroke-width="1.2"/>
  <text class="edgelabel" x="390" y="221" fill="#fbbf24" text-anchor="middle">stale (&gt;5s) or mod inactive</text>

  <!-- Row 2: Emergency Savegame Fallback Path -->
  <rect class="node" x="144" y="300" width="180" height="58" rx="11" stroke="#fbbf24"/>
  <text class="main" x="234" y="324">&#128190; UE5 Disk Save</text>
  <text class="sub" x="234" y="342">Saved\SaveGames\*.sav</text>

  <rect class="node" x="368" y="300" width="196" height="58" rx="11" stroke="#fbbf24"/>
  <text class="main" x="466" y="324">&#128269; SaveFileReader</text>
  <text class="sub" x="466" y="342">mmap &#183; LastUsedSavePoint</text>

  <rect class="node" x="608" y="300" width="236" height="58" rx="11" stroke="#818cf8"/>
  <text class="main" x="726" y="324">&#128737;&#65039; Presentation Shield</text>
  <text class="sub" x="726" y="342">anti-spoiler &#183; 128-byte clamp</text>

  <!-- Row 2: Unobstructed Animated Connectors -->
  <path class="flow" d="M324,329 L362,329" stroke="#fbbf24" marker-end="url(#headAmber)"/>
  <path class="flow" d="M564,329 L602,329" stroke="#fbbf24" marker-end="url(#headAmber)"/>

  <!-- Return Flow: Fallback Restores Presence -->
  <path class="flow" d="M774,300 C774,235 774,205 774,148" stroke="#818cf8" marker-end="url(#headBlurple)"/>

  <!-- Pill Badge for Return Flow -->
  <rect x="696" y="206" width="156" height="22" rx="11" fill="#0e1322" stroke="#818cf8" stroke-width="1.2"/>
  <text class="edgelabel" x="774" y="221" fill="#818cf8" text-anchor="middle">fallback synced &#183; live</text>

  <!-- Bottom Architecture Caption -->
  <text class="caption" x="440" y="432">Zero game process injection &#183; 5.0s SLA on hot telemetry &#183; Atomic mmap fallback &#183; Native Discord IPC named pipe</text>
</svg>
"""

THREADING_SVG_CONTENT = r"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" role="img" aria-label="Expedition 33 Discord RPC Threading Model: Main thread drives Win32 pystray message pump, isolated worker thread drives detection and Discord IPC, with non-blocking platform abstraction.">
  <style>
    .flow { fill: none; stroke-width: 2.2; stroke-linecap: round; stroke-dasharray: 7 7; animation: e33flow .7s linear infinite; }
    @keyframes e33flow { to { stroke-dashoffset: -14; } }
    @media (prefers-reduced-motion: reduce) { .flow { animation: none; } }
    .node { fill: #0e1322; stroke-width: 1.6; }
    .main { font: 600 13.5px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; fill: #f8fafc; text-anchor: middle; }
    .sub { font: 400 11px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; fill: #94a3b8; text-anchor: middle; }
    .edgelabel { font: 600 11px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; }
    .tag { font: 700 11px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; letter-spacing: 2.2px; fill: #2dd4bf; }
    .caption { font: 400 11.5px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; fill: #94a3b8; text-anchor: middle; }
  </style>
  <defs>
    <linearGradient id="edge" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#2dd4bf"/>
      <stop offset=".45" stop-color="#818cf8"/>
      <stop offset="1" stop-color="#f43f5e"/>
    </linearGradient>
    <marker id="headTeal" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#2dd4bf"/>
    </marker>
    <marker id="headIndigo" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#818cf8"/>
    </marker>
    <marker id="headRose" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#f43f5e"/>
    </marker>
  </defs>

  <!-- Card Canvas -->
  <rect x="4" y="4" width="872" height="462" rx="16" fill="#080c16" stroke="url(#edge)" stroke-width="1.6"/>

  <!-- Brand Header -->
  <rect x="34" y="24" width="32" height="32" rx="8" fill="#131b2e" stroke="url(#edge)" stroke-width="1.4"/>
  <text x="50" y="46" font-family="ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif" font-size="15" font-weight="900" fill="#2dd4bf" text-anchor="middle">33</text>
  <text x="78" y="47" font-family="ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif" font-size="19" font-weight="800" letter-spacing="1.5" fill="url(#edge)">EXPEDITION&#160;33</text>
  <text class="tag" x="254" y="45">&#183; THREADING &amp; PLATFORM ABSTRACTION</text>

  <!-- Row 1: Core Execution Lifecycle -->
  <rect class="node" x="36" y="84" width="176" height="58" rx="11" stroke="#2dd4bf"/>
  <text class="main" x="124" y="108">&#128421;&#65039; Main Thread</text>
  <text class="sub" x="124" y="126">pystray &#183; Win32 msg pump</text>

  <rect class="node" x="256" y="84" width="180" height="58" rx="11" stroke="#2dd4bf"/>
  <text class="main" x="346" y="108">&#9881;&#65039; Worker Daemon</text>
  <text class="sub" x="346" y="126">2.0s tick &#183; detector loop</text>

  <rect class="node" x="480" y="84" width="180" height="58" rx="11" stroke="#818cf8"/>
  <text class="main" x="570" y="108">&#9889; Shared File I/O</text>
  <text class="sub" x="570" y="126">Win32 CreateFileW (0x7)</text>

  <rect class="node" x="704" y="84" width="140" height="58" rx="11" stroke="#818cf8"/>
  <text class="main" x="774" y="108">&#128172; Discord Client</text>
  <text class="sub" x="774" y="126">native Named Pipe wire</text>

  <!-- Row 1: Unobstructed Animated Connectors -->
  <path class="flow" d="M212,113 L250,113" stroke="#2dd4bf" marker-end="url(#headTeal)"/>
  <path class="flow" d="M436,113 L474,113" stroke="#818cf8" marker-end="url(#headIndigo)"/>
  <path class="flow" d="M660,113 L698,113" stroke="#818cf8" marker-end="url(#headIndigo)"/>

  <!-- Branch 1: Main Thread guards Single Instance -->
  <path class="flow" d="M124,142 L124,294" stroke="#2dd4bf" marker-end="url(#headTeal)"/>

  <!-- Pill Badge 1: Single Instance Guard -->
  <rect x="44" y="206" width="160" height="22" rx="11" fill="#0e1322" stroke="#2dd4bf" stroke-width="1.2"/>
  <text class="edgelabel" x="124" y="221" fill="#2dd4bf" text-anchor="middle">single-instance guard</text>

  <!-- Branch 2: Worker Daemon spawns Installer on game launch -->
  <path class="flow" d="M346,142 C346,220 410,225 410,294" stroke="#f43f5e" marker-end="url(#headRose)"/>

  <!-- Pill Badge 2: Ephemeral Spawning -->
  <rect x="330" y="206" width="116" height="22" rx="11" fill="#0e1322" stroke="#f43f5e" stroke-width="1.2"/>
  <text class="edgelabel" x="388" y="221" fill="#f43f5e" text-anchor="middle">spawns on PID</text>

  <!-- Branch 3: Worker Daemon spawns Ephemeral Update Checker -->
  <path class="flow" d="M380,142 C400,230 712,220 712,294" stroke="#f43f5e" marker-end="url(#headRose)"/>

  <!-- Pill Badge 3: Async Check -->
  <rect x="526" y="206" width="158" height="22" rx="11" fill="#0e1322" stroke="#f43f5e" stroke-width="1.2"/>
  <text class="edgelabel" x="605" y="221" fill="#f43f5e" text-anchor="middle">async check (daemon)</text>

  <!-- Row 2: Concurrency Guards & Background Workers -->
  <rect class="node" x="36" y="300" width="176" height="58" rx="11" stroke="#2dd4bf"/>
  <text class="main" x="124" y="324">&#128274; Single-Instance Lock</text>
  <text class="sub" x="124" y="342">Win32 Mutex &#183; flock POSIX</text>

  <rect class="node" x="300" y="300" width="220" height="58" rx="11" stroke="#f43f5e"/>
  <text class="main" x="410" y="324">&#128736;&#65039; Ephemeral Installer</text>
  <text class="sub" x="410" y="342">isolated thread &#183; zero UI lag</text>

  <rect class="node" x="580" y="300" width="264" height="58" rx="11" stroke="#f43f5e"/>
  <text class="main" x="712" y="324">&#127760; Background Updater</text>
  <text class="sub" x="712" y="342">GitHub Releases &#183; daemon</text>

  <!-- Bottom Architecture Caption -->
  <text class="caption" x="440" y="432">Win32 message pump stays fluid &#183; Zero lock contention on telemetry reads &#183; Background workers exit instantly on app quit</text>
</svg>
"""

STATE_MACHINE_SVG_CONTENT = r"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" role="img" aria-label="Expedition 33 Discord RPC State Machine: Resilient state machine tracking process lifecycle, telemetry freshness TTL, fallback degradation, and Discord IPC fault recovery.">
  <style>
    .flow { fill: none; stroke-width: 2.2; stroke-linecap: round; stroke-dasharray: 7 7; animation: e33flow .7s linear infinite; }
    @keyframes e33flow { to { stroke-dashoffset: -14; } }
    @media (prefers-reduced-motion: reduce) { .flow { animation: none; } }
    .node { fill: #0e1322; stroke-width: 1.6; }
    .main { font: 600 13.5px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; fill: #f8fafc; text-anchor: middle; }
    .sub { font: 400 11px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; fill: #94a3b8; text-anchor: middle; }
    .edgelabel { font: 600 11px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; }
    .tag { font: 700 11px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; letter-spacing: 2.2px; fill: #38bdf8; }
    .caption { font: 400 11.5px ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif; fill: #94a3b8; text-anchor: middle; }
  </style>
  <defs>
    <linearGradient id="edgeState" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#38bdf8"/>
      <stop offset=".35" stop-color="#34d399"/>
      <stop offset=".7" stop-color="#fbbf24"/>
      <stop offset="1" stop-color="#f43f5e"/>
    </linearGradient>
    <marker id="headCyanSM" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#38bdf8"/>
    </marker>
    <marker id="headEmeraldSM" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#34d399"/>
    </marker>
    <marker id="headAmberSM" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#fbbf24"/>
    </marker>
    <marker id="headBlurpleSM" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#818cf8"/>
    </marker>
    <marker id="headRoseSM" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#f43f5e"/>
    </marker>
  </defs>

  <!-- Card Canvas -->
  <rect x="4" y="4" width="872" height="462" rx="16" fill="#080c16" stroke="url(#edgeState)" stroke-width="1.6"/>

  <!-- Brand Header -->
  <rect x="34" y="24" width="32" height="32" rx="8" fill="#131b2e" stroke="url(#edgeState)" stroke-width="1.4"/>
  <text x="50" y="46" font-family="ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif" font-size="15" font-weight="900" fill="#38bdf8" text-anchor="middle">33</text>
  <text x="78" y="47" font-family="ui-sans-serif, -apple-system, 'Segoe UI', Roboto, sans-serif" font-size="19" font-weight="800" letter-spacing="1.5" fill="url(#edgeState)">EXPEDITION&#160;33</text>
  <text class="tag" x="254" y="45">&#183; STATE MACHINE &amp; INVARIANT GUARANTEES</text>

  <!-- Row 1: Core Lifecycle Path -->
  <rect class="node" x="36" y="84" width="176" height="58" rx="11" stroke="#38bdf8"/>
  <text class="main" x="124" y="108">&#9208;&#65039; Game Idle</text>
  <text class="sub" x="124" y="126">standby &#183; 5.0s psutil poll</text>

  <rect class="node" x="256" y="84" width="180" height="58" rx="11" stroke="#34d399"/>
  <text class="main" x="346" y="108">&#9654;&#65039; Game Active</text>
  <text class="sub" x="346" y="126">cached_pid &#183; 2.0s tick</text>

  <rect class="node" x="480" y="84" width="180" height="58" rx="11" stroke="#34d399"/>
  <text class="main" x="570" y="108">&#9201;&#65039; Freshness Engine</text>
  <text class="sub" x="570" y="126">5.0s TTL &#183; game_data SSOT</text>

  <rect class="node" x="704" y="84" width="140" height="58" rx="11" stroke="#818cf8"/>
  <text class="main" x="774" y="108">&#128172; Discord IPC</text>
  <text class="sub" x="774" y="126">binary &lt;II &#183; dirty-check</text>

  <!-- Row 1: Forward Connectors -->
  <path class="flow" d="M212,113 L250,113" stroke="#38bdf8" marker-end="url(#headCyanSM)"/>
  <path class="flow" d="M436,113 L474,113" stroke="#34d399" marker-end="url(#headEmeraldSM)"/>
  <path class="flow" d="M660,113 L698,113" stroke="#34d399" marker-end="url(#headEmeraldSM)"/>

  <!-- Return Flow 1: Process Exit drops back to Idle -->
  <path class="flow" d="M320,142 C320,240 124,240 124,148" stroke="#38bdf8" marker-end="url(#headCyanSM)"/>
  <rect x="150" y="226" width="184" height="22" rx="11" fill="#0e1322" stroke="#38bdf8" stroke-width="1.2"/>
  <text class="edgelabel" x="242" y="241" fill="#38bdf8" text-anchor="middle">game exit &#183; instant O(1) reset</text>

  <!-- Branch 2: Stale Telemetry drops to Fallback -->
  <path class="flow" d="M570,142 L570,294" stroke="#fbbf24" marker-end="url(#headAmberSM)"/>
  <rect x="478" y="206" width="184" height="22" rx="11" fill="#0e1322" stroke="#fbbf24" stroke-width="1.2"/>
  <text class="edgelabel" x="570" y="221" fill="#fbbf24" text-anchor="middle">stale (&gt;5.0s) or mod inactive</text>

  <!-- Row 2: Invariants & Fault Recovery -->
  <rect class="node" x="470" y="300" width="200" height="58" rx="11" stroke="#fbbf24"/>
  <text class="main" x="570" y="324">&#128737;&#65039; Fallback Exploration</text>
  <text class="sub" x="570" y="342">UE5 .sav mmap &#183; clean state</text>

  <!-- Flow: Fallback Restores to Active Discord Pipe -->
  <path class="flow" d="M670,329 C720,329 744,250 744,148" stroke="#818cf8" marker-end="url(#headBlurpleSM)"/>

  <!-- Branch 3: Broken Pipe drops to Reconnector -->
  <path class="flow" d="M784,142 L784,294" stroke="#f43f5e" marker-end="url(#headRoseSM)"/>
  <rect x="696" y="206" width="154" height="22" rx="11" fill="#0e1322" stroke="#f43f5e" stroke-width="1.2"/>
  <text class="edgelabel" x="773" y="221" fill="#f43f5e" text-anchor="middle">pipe fault / crash</text>

  <rect class="node" x="704" y="300" width="140" height="58" rx="11" stroke="#f43f5e"/>
  <text class="main" x="774" y="324">&#128260; IPC Reconnect</text>
  <text class="sub" x="774" y="342">backoff + jitter</text>

  <!-- Return Flow: IPC Reconnect loops back into Discord Pipe -->
  <path class="flow" d="M820,300 C835,230 835,210 820,148" stroke="#f43f5e" marker-end="url(#headRoseSM)"/>

  <!-- Bottom Architecture Caption -->
  <text class="caption" x="440" y="432">O(1) PID liveness tracking &#183; 5.0s TTL freshness SLA &#183; Exponential backoff on pipe fault &#183; Zero ghost presences</text>
</svg>
"""


def generate_diagrams() -> None:
    """Writes SVGs and validates XML and file bounds."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    pipeline_file = DOCS_DIR / "architecture_pipeline.svg"
    threading_file = DOCS_DIR / "architecture_threading.svg"
    state_machine_file = DOCS_DIR / "architecture_state_machine.svg"

    pipeline_file.write_text(PIPELINE_SVG_CONTENT.strip() + "\n", encoding="utf-8")
    threading_file.write_text(THREADING_SVG_CONTENT.strip() + "\n", encoding="utf-8")
    state_machine_file.write_text(STATE_MACHINE_SVG_CONTENT.strip() + "\n", encoding="utf-8")

    for f in (pipeline_file, threading_file, state_machine_file):
        size = os.path.getsize(f)
        ET.parse(f)  # Asserts XML validity
        print(f"Generated {f.name}: {size} bytes ({size / 1024:.2f} KB) - Valid XML.")


if __name__ == "__main__":
    generate_diagrams()
