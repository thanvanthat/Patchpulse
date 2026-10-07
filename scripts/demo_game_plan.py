"""Commit-by-commit plan for the "Ember Hollow" demo game repo.

Each release is a list of commits; each commit is a list of file operations:
  ("write", path, text)            create or overwrite a file
  ("append", path, text)           append text to a file
  ("replace", path, old, new)      replace exactly one occurrence of `old`

Five bugs are planted (see BUGS). Commits that introduce or fix a bug carry its id.
Nothing in this file's commit messages says "bug introduced" — it should read like real history.
"""

from dataclasses import dataclass, field

Op = tuple[str, ...]


@dataclass(frozen=True)
class CommitSpec:
    message: str
    ops: list[Op]
    introduces: str | None = None
    fixes: str | None = None


@dataclass(frozen=True)
class ReleaseSpec:
    tag: str
    notes: str
    commits: list[CommitSpec] = field(default_factory=list)


@dataclass(frozen=True)
class BugSpec:
    id: str
    title: str
    description: str
    area: str
    symptoms: list[str]
    affected_files: list[str]
    # A snippet present in the first affected file right after the bug is introduced
    # and gone after it is fixed. Used only by tests to prove the bug is really planted.
    evidence: str


BUGS: list[BugSpec] = [
    BugSpec(
        id="BUG-1",
        title="Save file corrupted when quitting",
        description=(
            "On quit the save is written from a daemon thread that opens the file with 'w' "
            "(truncating it) and is killed when the process exits, leaving an empty or "
            "partial save."
        ),
        area="save_system",
        symptoms=["save lost after quitting", "save file corrupted", "progress reset on load"],
        affected_files=["game/save_system.py", "game/main.py"],
        evidence="threading.Thread(target=_write, daemon=True).start()",
    ),
    BugSpec(
        id="BUG-2",
        title="Player moves too fast at high frame rates",
        description=(
            "Movement integration divides velocity by a hard-coded 60 instead of multiplying "
            "by frame delta, so movement speed scales with FPS (2.4x at the new 144 FPS cap)."
        ),
        area="movement",
        symptoms=["character too fast", "clipping through walls", "jumps too high on 144hz"],
        affected_files=["game/player_movement.py"],
        evidence="player.x += player.vx / 60",
    ),
    BugSpec(
        id="BUG-3",
        title="Audio cuts out after alt-tab",
        description=(
            "The output device is released when the window loses focus but never reopened "
            "when focus returns, so sound effects stay silent until restart."
        ),
        area="audio",
        symptoms=["no sound after alt-tab", "audio stops after minimizing", "sfx missing"],
        affected_files=["game/audio.py", "game/main.py"],
        evidence="def on_focus_gained() -> None:\n    if _current_music:",
    ),
    BugSpec(
        id="BUG-4",
        title="Inventory item duplication when splitting stacks",
        description=(
            "Splitting a stack with a full inventory calls add() for the split half without "
            "removing it from the source stack, duplicating items."
        ),
        area="inventory",
        symptoms=["items duplicated", "dupe glitch with right-click", "free items exploit"],
        affected_files=["game/inventory.py"],
        evidence="self.add(stack.item_id, half)\n            return",
    ),
    BugSpec(
        id="BUG-5",
        title="Co-op players disconnected every ~30 seconds",
        description=(
            "Heartbeat interval was raised to 45s while the server timeout stays 30s, so "
            "clients time out between heartbeats."
        ),
        area="networking",
        symptoms=["kicked from co-op", "disconnects every minute", "connection timed out"],
        affected_files=["game/networking.py"],
        evidence="HEARTBEAT_INTERVAL_S = 45",
    ),
]

# --------------------------------------------------------------------------- initial files

README = """# Ember Hollow

A small co-op survival platformer. Explore, gather, build, and survive the night.

## Run

    python -m game.main
"""

INIT = '''"""Ember Hollow — a small co-op survival platformer."""

VERSION = "0.0.0"
'''

CONFIG = '''"""Runtime configuration defaults."""

FPS_CAP = 60
WINDOW_TITLE = "Ember Hollow"
AUTOSAVE_MINUTES = 0
LANGUAGES = ["en"]
'''

MAIN = '''"""Game entry point and main loop."""

from game import audio, config, save_system, ui_menu
from game.player_movement import Player, update


def run() -> None:
    player = Player()
    state = {"player": {"x": player.x, "y": player.y}}
    audio.play_music("theme")
    ui_menu.show_main_menu()
    dt = 1.0 / config.FPS_CAP
    for _ in range(3):
        update(player, move_dir=1.0, jump=False, dt=dt)
    on_quit(state)


def on_quit(state: dict[str, object]) -> None:
    save_system.save("slot1", state)
    audio.shutdown()


if __name__ == "__main__":
    run()
'''

MOVEMENT = '''"""Player movement and simple platformer physics."""

from dataclasses import dataclass

GRAVITY = 30.0
WALK_SPEED = 6.0
JUMP_VELOCITY = 12.0


@dataclass
class Player:
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    on_ground: bool = True


def update(player: Player, move_dir: float, jump: bool, dt: float) -> None:
    player.vx = move_dir * WALK_SPEED
    if jump and player.on_ground:
        player.vy = JUMP_VELOCITY
        player.on_ground = False
    player.vy -= GRAVITY * dt
    player.x += player.vx * dt
    player.y += player.vy * dt
    if player.y <= 0.0:
        player.y = 0.0
        player.vy = 0.0
        player.on_ground = True
'''

INVENTORY = '''"""Inventory with stackable items."""

from dataclasses import dataclass, field

MAX_STACK = 64
SLOTS = 24


@dataclass
class Stack:
    item_id: str
    count: int


@dataclass
class Inventory:
    slots: list[Stack | None] = field(default_factory=lambda: [None] * SLOTS)

    def add(self, item_id: str, count: int) -> int:
        """Add items, filling existing stacks first. Returns the number that did not fit."""
        for stack in self.slots:
            if stack and stack.item_id == item_id and stack.count < MAX_STACK:
                moved = min(count, MAX_STACK - stack.count)
                stack.count += moved
                count -= moved
                if count == 0:
                    return 0
        for i, stack in enumerate(self.slots):
            if stack is None:
                moved = min(count, MAX_STACK)
                self.slots[i] = Stack(item_id, moved)
                count -= moved
                if count == 0:
                    return 0
        return count

    def total(self, item_id: str) -> int:
        return sum(s.count for s in self.slots if s and s.item_id == item_id)
'''

SAVE = '''"""Save and load game state as JSON with atomic writes."""

import json
import os
from pathlib import Path
from typing import Any

SAVE_DIR = Path.home() / ".ember_hollow" / "saves"


def save(slot: str, state: dict[str, Any]) -> Path:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    path = SAVE_DIR / f"{slot}.json"
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return path


def load(slot: str) -> dict[str, Any]:
    path = SAVE_DIR / f"{slot}.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)
'''

AUDIO = '''"""Audio manager: music, sound effects and the output device."""

MASTER_VOLUME = 0.8
_device_open = True
_current_music: str | None = None


def play_music(track: str) -> None:
    global _current_music
    _current_music = track


def play_sfx(name: str) -> bool:
    """Returns False when the sound could not be played."""
    return _device_open


def shutdown() -> None:
    global _device_open
    _device_open = False
'''

UI_MENU = '''"""Main menu, pause menu and settings screens."""

MENU_ITEMS = ["Continue", "New Game", "Settings", "Quit"]


def show_main_menu() -> list[str]:
    return list(MENU_ITEMS)


def show_pause_menu() -> list[str]:
    return ["Resume", "Settings", "Quit to Menu"]
'''

NETWORKING = '''"""Co-op networking: peer connection, heartbeats and state sync."""

HEARTBEAT_INTERVAL_S = 5
SERVER_TIMEOUT_S = 30
MAX_PLAYERS = 4


class Connection:
    def __init__(self, host: str, port: int = 7777) -> None:
        self.host = host
        self.port = port
        self.last_heartbeat = 0.0
        self.connected = False

    def connect(self) -> bool:
        self.connected = True
        return True

    def tick(self, now: float) -> None:
        if now - self.last_heartbeat >= HEARTBEAT_INTERVAL_S:
            self.send_heartbeat(now)

    def send_heartbeat(self, now: float) -> None:
        self.last_heartbeat = now

    def is_timed_out(self, now: float) -> bool:
        return now - self.last_heartbeat > SERVER_TIMEOUT_S
'''

STRINGS_EN = """{
  "menu.continue": "Continue",
  "menu.new_game": "New Game",
  "menu.settings": "Settings",
  "menu.quit": "Quit"
}
"""

# --------------------------------------------------------------------------- releases

RELEASES: list[ReleaseSpec] = [
    ReleaseSpec(
        tag="v0.1",
        notes="First playable build: movement, inventory, saving, music and menus.",
        commits=[
            CommitSpec(
                "Initial project structure",
                [
                    ("write", "README.md", README),
                    ("write", "game/__init__.py", INIT),
                    ("write", "game/config.py", CONFIG),
                ],
            ),
            CommitSpec(
                "Add player movement with basic platformer physics",
                [("write", "game/player_movement.py", MOVEMENT)],
            ),
            CommitSpec(
                "Add inventory with stackable items",
                [("write", "game/inventory.py", INVENTORY)],
            ),
            CommitSpec(
                "Add save system with atomic JSON writes",
                [("write", "game/save_system.py", SAVE)],
            ),
            CommitSpec(
                "Add audio manager and background music",
                [("write", "game/audio.py", AUDIO)],
            ),
            CommitSpec(
                "Add main menu, pause menu and game loop",
                [
                    ("write", "game/ui_menu.py", UI_MENU),
                    ("write", "game/main.py", MAIN),
                    ("write", "assets/strings/en.json", STRINGS_EN),
                ],
            ),
        ],
    ),
    ReleaseSpec(
        tag="v0.2",
        notes=(
            "Co-op is here! Play with up to 4 friends (beta).\n"
            "- New settings screen with volume sliders\n"
            "- Inventory can be sorted by rarity\n"
            "- Footsteps now have variations\n"
            "- Smoother gameplay: FPS cap raised to 144"
        ),
        commits=[
            CommitSpec(
                "Add co-op networking prototype with heartbeats",
                [("write", "game/networking.py", NETWORKING)],
            ),
            CommitSpec(
                "ui_menu: add settings screen with volume sliders",
                [
                    (
                        "append",
                        "game/ui_menu.py",
                        """

def show_settings() -> dict[str, float]:
    return {"master": 0.8, "music": 0.6, "sfx": 0.8}
""",
                    )
                ],
            ),
            CommitSpec(
                "player_movement: simplify integration step",
                [
                    (
                        "replace",
                        "game/player_movement.py",
                        "    player.x += player.vx * dt\n    player.y += player.vy * dt\n",
                        "    # Integrate per frame; velocities are tuned for a 60 Hz tick.\n"
                        "    player.x += player.vx / 60\n    player.y += player.vy / 60\n",
                    )
                ],
                introduces="BUG-2",
            ),
            CommitSpec(
                "inventory: add sorting by rarity",
                [
                    (
                        "append",
                        "game/inventory.py",
                        """
    def sort_by_rarity(self, rarity: dict[str, int]) -> None:
        filled = [s for s in self.slots if s]
        filled.sort(key=lambda s: (-rarity.get(s.item_id, 0), s.item_id))
        self.slots = filled + [None] * (SLOTS - len(filled))
""",
                    )
                ],
            ),
            CommitSpec(
                "audio: add footstep sound variations",
                [
                    (
                        "append",
                        "game/audio.py",
                        """

FOOTSTEP_VARIANTS = ["step_dirt_1", "step_dirt_2", "step_dirt_3"]


def footstep(i: int) -> bool:
    return play_sfx(FOOTSTEP_VARIANTS[i % len(FOOTSTEP_VARIANTS)])
""",
                    )
                ],
            ),
            CommitSpec(
                "config: raise default FPS cap to 144",
                [("replace", "game/config.py", "FPS_CAP = 60", "FPS_CAP = 144")],
            ),
        ],
    ),
    ReleaseSpec(
        tag="v0.3",
        notes=(
            "- Autosave every 5 minutes\n"
            "- Lobby codes for co-op\n"
            "- Faster quitting: the game now closes instantly\n"
            "- Controller support in menus\n"
            "- Max stack size raised to 99\n"
            "- Hindi and Tamil translations"
        ),
        commits=[
            CommitSpec(
                "save_system: add autosave every 5 minutes",
                [
                    (
                        "append",
                        "game/save_system.py",
                        """

def autosave(state: dict[str, Any]) -> Path:
    return save("autosave", state)
""",
                    ),
                    ("replace", "game/config.py", "AUTOSAVE_MINUTES = 0", "AUTOSAVE_MINUTES = 5"),
                ],
            ),
            CommitSpec(
                "networking: add lobby codes",
                [
                    (
                        "append",
                        "game/networking.py",
                        """

def lobby_code(host: str, port: int) -> str:
    return f"{abs(hash((host, port))) % 1_000_000:06d}"
""",
                    )
                ],
            ),
            CommitSpec(
                "save_system: write save in background on quit to speed up shutdown",
                [
                    (
                        "append",
                        "game/save_system.py",
                        '''

def save_on_quit(slot: str, state: dict[str, Any]) -> None:
    """Write the save in the background so quitting is instant."""
    import threading

    def _write() -> None:
        path = SAVE_DIR / f"{slot}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(state, f)

    threading.Thread(target=_write, daemon=True).start()
''',
                    ),
                    (
                        "replace",
                        "game/main.py",
                        '    save_system.save("slot1", state)',
                        '    save_system.save_on_quit("slot1", state)',
                    ),
                ],
                introduces="BUG-1",
            ),
            CommitSpec(
                "ui_menu: add controller navigation",
                [
                    (
                        "append",
                        "game/ui_menu.py",
                        """

def navigate(index: int, direction: int, items: list[str]) -> int:
    return (index + direction) % len(items)
""",
                    )
                ],
            ),
            CommitSpec(
                "inventory: raise max stack size to 99",
                [("replace", "game/inventory.py", "MAX_STACK = 64", "MAX_STACK = 99")],
            ),
            CommitSpec(
                "i18n: add Hindi and Tamil translations",
                [
                    (
                        "write",
                        "assets/strings/hi.json",
                        '{\n  "menu.continue": "जारी रखें",\n  "menu.new_game": "नया खेल",\n'
                        '  "menu.settings": "सेटिंग्स",\n  "menu.quit": "बाहर निकलें"\n}\n',
                    ),
                    (
                        "write",
                        "assets/strings/ta.json",
                        '{\n  "menu.continue": "தொடரவும்",\n  "menu.new_game": "புதிய விளையாட்டு",\n'
                        '  "menu.settings": "அமைப்புகள்",\n  "menu.quit": "வெளியேறு"\n}\n',
                    ),
                    (
                        "replace",
                        "game/config.py",
                        'LANGUAGES = ["en"]',
                        'LANGUAGES = ["en", "hi", "ta"]',
                    ),
                ],
            ),
        ],
    ),
    ReleaseSpec(
        tag="v0.4",
        notes=(
            "- Fixed: characters moving too fast on high refresh rate monitors\n"
            "- Lower CPU usage when the game is in the background\n"
            "- Patch notes now shown on first launch\n"
            "- Smaller co-op packets\n"
            "- Quick-stack items into chests\n"
            "- New VSync option"
        ),
        commits=[
            CommitSpec(
                "player_movement: scale velocity by frame delta",
                [
                    (
                        "replace",
                        "game/player_movement.py",
                        "    # Integrate per frame; velocities are tuned for a 60 Hz tick.\n"
                        "    player.x += player.vx / 60\n    player.y += player.vy / 60\n",
                        "    player.x += player.vx * dt\n    player.y += player.vy * dt\n",
                    )
                ],
                fixes="BUG-2",
            ),
            CommitSpec(
                "audio: release output device when window loses focus",
                [
                    (
                        "append",
                        "game/audio.py",
                        '''

def on_focus_lost() -> None:
    """Release the output device while unfocused to save CPU."""
    global _device_open
    _device_open = False


def on_focus_gained() -> None:
    if _current_music:
        play_music(_current_music)
''',
                    ),
                    (
                        "replace",
                        "game/main.py",
                        '\n\nif __name__ == "__main__":',
                        """

def on_focus_changed(focused: bool) -> None:
    if focused:
        audio.on_focus_gained()
    else:
        audio.on_focus_lost()


if __name__ == "__main__":""",
                    ),
                ],
                introduces="BUG-3",
            ),
            CommitSpec(
                "ui_menu: show patch notes on first launch",
                [
                    (
                        "append",
                        "game/ui_menu.py",
                        """

def should_show_patch_notes(last_seen: str, current: str) -> bool:
    return last_seen != current
""",
                    )
                ],
            ),
            CommitSpec(
                "networking: compress state packets",
                [
                    (
                        "append",
                        "game/networking.py",
                        """

def pack_state(state: bytes) -> bytes:
    import zlib

    return zlib.compress(state, level=6)
""",
                    )
                ],
            ),
            CommitSpec(
                "inventory: add quick-stack to nearby chest",
                [
                    (
                        "append",
                        "game/inventory.py",
                        """
    def quick_stack(self, chest: "Inventory") -> None:
        for i, stack in enumerate(self.slots):
            if stack and chest.total(stack.item_id) > 0:
                left = chest.add(stack.item_id, stack.count)
                self.slots[i] = Stack(stack.item_id, left) if left else None
""",
                    )
                ],
            ),
            CommitSpec(
                "config: add VSync option",
                [("append", "game/config.py", "VSYNC = True\n")],
            ),
        ],
    ),
    ReleaseSpec(
        tag="v0.5",
        notes=(
            "- Fixed: rare save corruption when closing the game\n"
            "- Right-click to split item stacks\n"
            "- Music ducks during dialogue\n"
            "- Fixed: settings not saved between sessions\n"
            "- Sprinting with stamina\n"
            "- Ping shown in co-op HUD"
        ),
        commits=[
            CommitSpec(
                "save_system: save synchronously on quit using atomic write",
                [
                    (
                        "replace",
                        "game/save_system.py",
                        '''    """Write the save in the background so quitting is instant."""
    import threading

    def _write() -> None:
        path = SAVE_DIR / f"{slot}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(state, f)

    threading.Thread(target=_write, daemon=True).start()
''',
                        '''    """Save synchronously on quit; atomic write keeps saves safe."""
    save(slot, state)
''',
                    )
                ],
                fixes="BUG-1",
            ),
            CommitSpec(
                "inventory: allow splitting stacks with right-click",
                [
                    (
                        "append",
                        "game/inventory.py",
                        '''
    def split_stack(self, index: int) -> None:
        """Right-click: move half of a stack into the first empty slot."""
        stack = self.slots[index]
        if stack is None or stack.count < 2:
            return
        half = stack.count // 2
        target = next((i for i, s in enumerate(self.slots) if s is None), None)
        if target is None:
            # Inventory full: merge the half into a matching stack instead.
            self.add(stack.item_id, half)
            return
        self.slots[target] = Stack(stack.item_id, half)
        stack.count -= half
''',
                    )
                ],
                introduces="BUG-4",
            ),
            CommitSpec(
                "audio: duck music volume during dialogue",
                [
                    (
                        "append",
                        "game/audio.py",
                        """

def music_volume(in_dialogue: bool) -> float:
    return MASTER_VOLUME * (0.3 if in_dialogue else 1.0)
""",
                    )
                ],
            ),
            CommitSpec(
                "ui_menu: persist settings to disk",
                [
                    (
                        "append",
                        "game/ui_menu.py",
                        """

def settings_path() -> str:
    return "~/.ember_hollow/settings.json"
""",
                    )
                ],
            ),
            CommitSpec(
                "player_movement: add sprint with stamina",
                [
                    (
                        "append",
                        "game/player_movement.py",
                        """

SPRINT_MULTIPLIER = 1.6


def sprint_speed(stamina: float) -> float:
    return WALK_SPEED * (SPRINT_MULTIPLIER if stamina > 0 else 1.0)
""",
                    )
                ],
            ),
            CommitSpec(
                "networking: show ping in HUD",
                [
                    (
                        "append",
                        "game/networking.py",
                        """

def format_ping(ms: float) -> str:
    return f"{ms:.0f} ms"
""",
                    )
                ],
            ),
        ],
    ),
    ReleaseSpec(
        tag="v0.6",
        notes=(
            "- Fixed: sound not coming back after alt-tabbing\n"
            "- Co-op uses less bandwidth (great for mobile hotspots)\n"
            "- Item tooltips\n"
            "- Colorblind mode\n"
            "- Cloud save metadata\n"
            "- Jump height tweaked"
        ),
        commits=[
            CommitSpec(
                "audio: reopen output device when window regains focus",
                [
                    (
                        "replace",
                        "game/audio.py",
                        "def on_focus_gained() -> None:\n    if _current_music:",
                        "def on_focus_gained() -> None:\n    global _device_open\n"
                        "    _device_open = True\n    if _current_music:",
                    )
                ],
                fixes="BUG-3",
            ),
            CommitSpec(
                "networking: send heartbeats less often to reduce bandwidth",
                [
                    (
                        "replace",
                        "game/networking.py",
                        "HEARTBEAT_INTERVAL_S = 5",
                        "HEARTBEAT_INTERVAL_S = 45",
                    )
                ],
                introduces="BUG-5",
            ),
            CommitSpec(
                "inventory: add item tooltips",
                [
                    (
                        "append",
                        "game/inventory.py",
                        """
    def tooltip(self, index: int) -> str:
        stack = self.slots[index]
        return f"{stack.item_id} x{stack.count}" if stack else ""
""",
                    )
                ],
            ),
            CommitSpec(
                "ui_menu: add colorblind mode",
                [
                    (
                        "append",
                        "game/ui_menu.py",
                        """

COLORBLIND_MODES = ["off", "protanopia", "deuteranopia", "tritanopia"]
""",
                    )
                ],
            ),
            CommitSpec(
                "save_system: add cloud save metadata",
                [
                    (
                        "append",
                        "game/save_system.py",
                        """

def metadata(slot: str) -> dict[str, Any]:
    path = SAVE_DIR / f"{slot}.json"
    return {"slot": slot, "bytes": path.stat().st_size if path.exists() else 0}
""",
                    )
                ],
            ),
            CommitSpec(
                "player_movement: tweak jump height",
                [
                    (
                        "replace",
                        "game/player_movement.py",
                        "JUMP_VELOCITY = 12.0",
                        "JUMP_VELOCITY = 13.5",
                    )
                ],
            ),
        ],
    ),
    ReleaseSpec(
        tag="v0.7",
        notes=(
            "- Co-op reconnects automatically after a timeout\n"
            "- Redesigned inventory screen\n"
            "- New boss music\n"
            "- Ledge grabbing\n"
            "- Smaller save files"
        ),
        commits=[
            CommitSpec(
                "networking: retry connection once on timeout",
                [
                    (
                        "append",
                        "game/networking.py",
                        """

def reconnect_if_needed(conn: Connection, now: float) -> None:
    if conn.is_timed_out(now):
        conn.connect()
        conn.send_heartbeat(now)
""",
                    )
                ],
            ),
            CommitSpec(
                "ui_menu: redesign inventory screen",
                [
                    (
                        "append",
                        "game/ui_menu.py",
                        """

INVENTORY_GRID = (6, 4)
""",
                    )
                ],
            ),
            CommitSpec(
                "audio: add boss music",
                [("append", "game/audio.py", '\n\nBOSS_TRACK = "ember_tyrant"\n')],
            ),
            CommitSpec(
                "player_movement: add ledge grab",
                [
                    (
                        "append",
                        "game/player_movement.py",
                        """

def can_grab_ledge(player: Player, ledge_y: float) -> bool:
    return not player.on_ground and abs(player.y - ledge_y) < 0.3
""",
                    )
                ],
            ),
            CommitSpec(
                "save_system: gzip save files",
                [
                    (
                        "append",
                        "game/save_system.py",
                        """

def save_compressed(slot: str, state: dict[str, Any]) -> Path:
    import gzip

    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    path = SAVE_DIR / f"{slot}.json.gz"
    path.write_bytes(gzip.compress(json.dumps(state).encode()))
    return path
""",
                    )
                ],
            ),
        ],
    ),
]
