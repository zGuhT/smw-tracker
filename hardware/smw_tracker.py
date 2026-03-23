"""
SNES tracker with:
- Keyhole timer going non-zero immediately triggers exit/split (not just latch)
- Game mode transitions also trigger exit (for switch palaces, boss rooms, etc)
- Run config loads on armed state, before auto-start
- More SMW hack keywords
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from core.level_names import resolve_level_name
from core.smw_levels import normalize_level_id
from hardware.qusb_client import QUsb2SnesClient
from hardware.smw_memory_map import (
    EXIT_STATE, GAME_MODE, KEYHOLE_TIMER, LEVEL_ID, LIVES, PLAYER_ANIM_STATE, PLAYER_X,
    MENU_MODES, GAMEPLAY_MODES, LEVEL_END_MODES, LEVEL_GAMEPLAY_ONLY,
    ANIM_DEATH, ANIM_DYING_BOUNCE,
)
from hardware.smw_detect import SMWDetector
from hardware.tracker_client import TrackerClient

log = logging.getLogger(__name__)


@dataclass
class HardwareGameState:
    rom_path: str | None = None
    game_name: str | None = None
    level_id: str | None = None
    level_name: str | None = None
    x_position: int | None = None
    player_anim_state: int | None = None
    exit_state: int | None = None
    keyhole_timer: int | None = None
    game_mode: int | None = None
    lives: int | None = None
    is_dead: bool = False
    has_exited: bool = False
    exit_type: str | None = None
    is_real_game: bool = False
    is_smw: bool = False


@dataclass
class TrackerConfig:
    progress_threshold: int = 24
    progress_interval_seconds: float = 2.5
    death_cooldown_seconds: float = 0.5
    exit_cooldown_seconds: float = 3.0
    exit_suppress_after_death_seconds: float = 6.0
    armed_delay_seconds: float = 1.0
    reconnect_delay_seconds: float = 3.0


class SMWTracker:
    def __init__(self, qusb: QUsb2SnesClient, client: TrackerClient,
                 config: TrackerConfig | None = None) -> None:
        self.qusb = qusb
        self.client = client
        self.config = config or TrackerConfig()

        self.last_state: HardwareGameState | None = None
        self.last_progress_x: int | None = None
        self.last_progress_time: float = 0.0
        self.last_death_time: float = 0.0
        self.last_exit_time: float = 0.0
        self.last_death_at_wallclock: float | None = None

        self.runtime_state: str = "idle"
        self.armed_since: float | None = None
        self.current_rom_path: str | None = None

        self.active_level_id: str | None = None
        self.active_level_name: str | None = None
        self.active_level_best_x: int | None = None
        self.active_level_deaths: int = 0
        self.keyhole_latched: bool = False
        self.exited_level_id: str | None = None  # Level we just exited, suppress re-exit

        self.active_run: dict[str, Any] | None = None
        self.run_level_index: int = -1
        self.split_start_time: float | None = None
        self.run_started: bool = False

        self.last_game_mode: int | None = None
        self.saw_menu: bool = False
        self.run_loaded_for: str | None = None
        self.smw_detector = SMWDetector()
        self._invalid_since: float | None = None

    # ── ROM helpers ──

    @staticmethod
    def _derive_game_name(rom_path: str | None) -> str | None:
        if not rom_path:
            return None
        cleaned = rom_path.replace("\x00", "").strip()
        base = os.path.basename(cleaned)
        name, _ = os.path.splitext(base)
        return name or base

    @staticmethod
    def _is_real_game_rom(rom_path: str | None) -> bool:
        if not rom_path:
            return False
        rp = rom_path.replace("\x00", "").strip().lower()
        if rp in {"", "no info"}:
            return False
        if any(rp.endswith(s) for s in ("/sd2snes/menu.bin", "/sd2snes/m3nu.bin", "menu.bin", "m3nu.bin")):
            return False
        return rp.endswith((".sfc", ".smc", ".fig", ".swc", ".gd3", ".bs"))

    def _is_smw_hack(self, game_name: str | None, rom_path: str | None = None) -> bool:
        """Detect SMW hack using ROM header reading + filename keywords."""
        return self.smw_detector.detect(
            rom_path=rom_path,
            game_name=game_name,
            qusb=self.qusb,
        )

    @staticmethod
    def _is_playable_level_id(level_id: str | None) -> bool:
        return level_id is not None and level_id not in {"00"}

    def _looks_like_valid_gameplay(self, state: HardwareGameState) -> bool:
        if not state.is_real_game:
            return False
        if state.is_smw:
            return (self._is_playable_level_id(state.level_id)
                    and state.x_position is not None and state.x_position >= 0)
        return True

    # ── Run management ──

    def _load_default_run(self, game_name: str) -> None:
        if self.run_loaded_for == game_name:
            return  # Already loaded
        try:
            from core.run_service import get_default_run_config
            config = get_default_run_config(game_name)
            if config and config.get("levels"):
                self.active_run = config
                log.info("Loaded run '%s' (%d levels, delay=%dms)",
                         config["run_name"], len(config["levels"]), config.get("start_delay_ms", 0))
            else:
                self.active_run = None
                log.info("No default run for %s", game_name)
        except Exception as exc:
            log.warning("Failed to load run: %s", exc)
            self.active_run = None
        self.run_loaded_for = game_name

    def _is_level_in_run(self, level_id: str) -> bool:
        if not self.active_run or not self.active_run.get("levels"):
            return True
        return any(rl.get("level_id") == level_id for rl in self.active_run["levels"])

    # ── Read hardware ──

    def read_state(self) -> HardwareGameState:
        rom_path = self.qusb.get_current_rom_path()
        is_real_game = self._is_real_game_rom(rom_path)

        if not is_real_game:
            if rom_path and self.current_rom_path:
                log.debug("Not a real game ROM: %s", rom_path)
            return HardwareGameState(rom_path=rom_path, is_real_game=False)

        game_name = self._derive_game_name(rom_path)
        is_smw = self._is_smw_hack(game_name, rom_path=rom_path)

        if is_smw:
            raw_level = self.qusb.read_u8(LEVEL_ID.address)
            raw_x = self.qusb.read_u16_le(PLAYER_X.address)
            raw_anim = self.qusb.read_u8(PLAYER_ANIM_STATE.address)
            raw_exit = self.qusb.read_u8(EXIT_STATE.address)
            raw_keyhole = self.qusb.read_u8(KEYHOLE_TIMER.address)
            raw_lives = self.qusb.read_u8(LIVES.address)
            raw_mode = self.qusb.read_u8(GAME_MODE.address)

            level_id = normalize_level_id(f"{raw_level:02X}")
            level_name = resolve_level_name(level_id, game_name=game_name)
            is_dead = self._infer_is_dead(anim_state=raw_anim, lives=raw_lives)

            # Basic exit from exit state byte
            has_exited = raw_exit is not None and raw_exit != 0

            return HardwareGameState(
                rom_path=rom_path, game_name=game_name,
                level_id=level_id, level_name=level_name,
                x_position=raw_x, player_anim_state=raw_anim,
                exit_state=raw_exit, keyhole_timer=raw_keyhole,
                game_mode=raw_mode, lives=raw_lives,
                is_dead=is_dead, has_exited=has_exited,
                exit_type=None, is_real_game=True, is_smw=True,
            )
        else:
            return HardwareGameState(rom_path=rom_path, game_name=game_name,
                                    is_real_game=True, is_smw=False)

    def _infer_is_dead(self, anim_state: int | None, lives: int | None) -> bool:
        if self.last_state and lives is not None and self.last_state.lives is not None:
            if lives < self.last_state.lives:
                return True
        # 0x09 = death animation, 0x01 = dying bounce (pit/lava)
        if anim_state in (ANIM_DEATH, ANIM_DYING_BOUNCE):
            return True
        return False

    # ── State machine ──

    def _stop_session_if_active(self) -> None:
        try:
            current = self.client.get_current_session()
            if current.get("is_active"):
                self.client.stop_session()
                log.info("Stopped active session for %s", current.get("game_name", "?"))
            else:
                # Also try direct stop in case of stale state
                from core.session_service import stop_active_session
                if stop_active_session(user_id=self.client.user_id):
                    log.info("Stopped stale active session (direct)")
        except Exception as exc:
            log.warning("Failed to stop session: %s", exc)

    def _ensure_session(self, game_name: str) -> None:
        """Create a session if one doesn't exist, so the UI shows the game immediately."""
        try:
            current = self.client.get_current_session()
            if current.get("is_active") and current.get("game_name") == game_name:
                return  # Session already exists for this game
            # Different game or no session — create one
            from core.session_service import get_or_create_active_session
            run_def_id = self.active_run.get("id") if self.active_run else None
            get_or_create_active_session(game_name=game_name, platform="SNES",
                                         run_definition_id=run_def_id,
                                         user_id=self.client.user_id)
        except Exception as exc:
            log.warning("Failed to ensure session: %s", exc)

    def _reset(self) -> None:
        self.runtime_state = "idle"
        self.armed_since = None
        self.last_state = None
        self.last_progress_x = None
        self.last_progress_time = 0.0
        self.active_level_id = None
        self.active_level_name = None
        self.active_level_best_x = None
        self.active_level_deaths = 0
        self.keyhole_latched = False
        self.exited_level_id = None
        self.active_run = None
        self.run_level_index = -1
        self.split_start_time = None
        self.run_started = False
        self.last_game_mode = None
        self.saw_menu = False
        self.run_loaded_for = None
        self.smw_detector.clear_cache()
        self._invalid_since = None

    def _check_run_auto_start(self, state: HardwareGameState, now: float) -> None:
        if not state.is_smw or state.game_mode is None:
            return

        if state.game_mode in MENU_MODES:
            self.saw_menu = True

        if (self.saw_menu
                and self.last_game_mode is not None
                and self.last_game_mode in MENU_MODES
                and state.game_mode in GAMEPLAY_MODES
                and not self.run_started):

            delay_ms = 0
            if self.active_run:
                delay_ms = self.active_run.get("start_delay_ms", 0)

            self.split_start_time = now + (delay_ms / 1000.0)
            self.run_started = True
            self.run_level_index = 0
            self.saw_menu = False

            # Record run_start event so the UI can show a live timer
            game_name = state.game_name or "Unknown Game"
            self.client.post_event(
                event_type="run_start",
                game_name=game_name,
                level_id=None, level_name=None, x_position=None,
                details={
                    "start_epoch": now,
                    "delay_ms": delay_ms,
                    "timer_epoch": self.split_start_time,
                    "run_name": self.active_run.get("run_name") if self.active_run else None,
                },
            )

            log.info("Run auto-started on menu→gameplay transition (mode %02X→%02X, delay=%dms)",
                     self.last_game_mode, state.game_mode, delay_ms)

        self.last_game_mode = state.game_mode

    def _update_runtime_state(self, state: HardwareGameState, now: float) -> None:
        if not state.is_real_game:
            if self.runtime_state != "idle" or self.current_rom_path:
                log.info("Left game (rom=%s), stopping session", state.rom_path)
                self._stop_session_if_active()
                self._reset()
            self.current_rom_path = None
            return

        if self.current_rom_path and state.rom_path != self.current_rom_path:
            if self.runtime_state in ("armed", "playing"):
                self._stop_session_if_active()
            self._reset()

        self.current_rom_path = state.rom_path

        # Only track SMW games — skip non-SMW entirely
        if not state.is_smw:
            if self.runtime_state != "idle":
                self._stop_session_if_active()
                self._reset()
            return

        valid = self._looks_like_valid_gameplay(state)

        if self.runtime_state == "idle":
            if valid:
                self.runtime_state = "armed"
                self.armed_since = now
                self._invalid_since = None
                # Only stop lingering session if it's for a DIFFERENT game
                try:
                    current = self.client.get_current_session()
                    if current.get("is_active") and current.get("game_name") != state.game_name:
                        self._stop_session_if_active()
                except Exception:
                    pass
                if state.game_name:
                    self._ensure_session(state.game_name)
                log.info("Armed for %s", state.game_name)
        elif self.runtime_state == "armed":
            if not valid:
                # Grace period — don't drop to idle immediately (screen transitions)
                if self._invalid_since is None:
                    self._invalid_since = now
                elif now - self._invalid_since > 5.0:
                    self.runtime_state = "idle"
                    self.armed_since = None
                    self._invalid_since = None
            else:
                self._invalid_since = None
                if self.armed_since and (now - self.armed_since) >= self.config.armed_delay_seconds:
                    self.runtime_state = "playing"
                    log.info("Playing: %s", state.game_name)
        elif self.runtime_state == "playing":
            if not valid:
                # Grace period — don't stop immediately (level transitions, overworld)
                if self._invalid_since is None:
                    self._invalid_since = now
                elif now - self._invalid_since > 10.0:
                    log.info("Lost valid gameplay for >10s, stopping")
                    self._stop_session_if_active()
                    self._reset()
            else:
                self._invalid_since = None

    # ── Exit detection (multiple methods) ──

    def _should_emit_exit(self, state: HardwareGameState, now: float) -> tuple[bool, str]:
        """
        Check multiple exit conditions. Returns (should_exit, exit_type).
        Exit types: 'normal', 'secret', 'special'
        
        Triggers:
        1. Exit state byte goes non-zero (standard goal tape)
        2. Keyhole timer goes non-zero (keyhole/secret exit)
        3. Game mode transitions to a level-end mode (switch palace, boss, etc)
        4. Level ID changes after meaningful progress
        """
        if not state.is_smw or self.last_state is None:
            return False, "normal"
        if now - self.last_exit_time < self.config.exit_cooldown_seconds:
            return False, "normal"
        if (self.last_death_at_wallclock is not None
                and (now - self.last_death_at_wallclock) < self.config.exit_suppress_after_death_seconds):
            return False, "normal"
        if not self._is_playable_level_id(self.last_state.level_id):
            return False, "normal"
        # Don't re-exit a level we already exited
        if self.last_state.level_id == self.exited_level_id:
            return False, "normal"

        # Method 1: Keyhole timer just went non-zero (secret exit)
        if (state.keyhole_timer is not None and state.keyhole_timer > 0
                and (self.last_state.keyhole_timer is None or self.last_state.keyhole_timer == 0)):
            log.info("Exit detected: keyhole timer activated (%d)", state.keyhole_timer)
            return True, "secret"

        # Method 2: Exit state byte went non-zero (normal goal tape)
        if state.has_exited and not self.last_state.has_exited:
            exit_type = "secret" if self.keyhole_latched else "normal"
            return True, exit_type

        # Method 3: Game mode changed to a level-end mode
        if (state.game_mode is not None and self.last_state.game_mode is not None
                and state.game_mode in LEVEL_END_MODES
                and self.last_state.game_mode not in LEVEL_END_MODES):
            log.info("Exit detected: game mode changed to %02X (level end)", state.game_mode)
            exit_type = "secret" if self.keyhole_latched else "special"
            return True, exit_type

        # Method 4: Level ID changed after meaningful progress
        # Only trigger if the level ID changed while game mode stays in normal gameplay
        # (door transitions briefly change game mode, so this avoids false exits in fortress hacks)
        level_changed = (state.level_id is not None and self.last_state.level_id is not None
                         and state.level_id != self.last_state.level_id)
        progressed_enough = self.active_level_best_x is not None and self.active_level_best_x >= 0x100
        new_level_valid = self._is_playable_level_id(state.level_id)
        # Game mode should be in active level gameplay (0x14 only, not transitioning)
        game_mode_stable = (state.game_mode is not None
                            and state.game_mode in LEVEL_GAMEPLAY_ONLY
                            and self.last_state.game_mode in LEVEL_GAMEPLAY_ONLY)

        if level_changed and progressed_enough and new_level_valid and game_mode_stable:
            exit_type = "secret" if self.keyhole_latched else "normal"
            return True, exit_type

        return False, "normal"

    def _emit_exit_and_split(self, previous: HardwareGameState, state: HardwareGameState,
                             game_name: str, exit_type: str, now: float) -> None:
        split_level_id = previous.level_id or ""
        if exit_type == "secret":
            split_level_id = f"{split_level_id}:secret"

        split_level_name = previous.level_name or self.active_level_name
        if split_level_name and exit_type == "secret":
            split_level_name = f"{split_level_name} (Secret)"

        split_ms = None
        if self.split_start_time is not None:
            split_ms = max(0, int((now - self.split_start_time) * 1000))

        try:
            current_session = self.client.get_current_session()
            session_id = current_session.get("id")
        except Exception:
            session_id = None

        self.client.post_event(
            event_type="exit", game_name=game_name,
            level_id=previous.level_id, level_name=previous.level_name,
            x_position=self.active_level_best_x or previous.x_position,
            details={
                "split_ms": split_ms, "death_count": self.active_level_deaths,
                "exit_type": exit_type, "keyhole_latched": self.keyhole_latched,
                "run_level_index": self.run_level_index,
                "game_mode": state.game_mode,
            },
        )

        if session_id and split_ms is not None and split_level_id:
            try:
                self.client.record_split(
                    session_id=session_id, game_name=game_name,
                    level_id=split_level_id, level_name=split_level_name,
                    split_ms=split_ms, entered_at=self.split_start_time or now,
                    exited_at=now, death_count=self.active_level_deaths,
                    best_x=self.active_level_best_x,
                )
                log.info("Split: %s [%s] = %dms (%d deaths)",
                         split_level_name or split_level_id, exit_type, split_ms, self.active_level_deaths)
            except Exception as exc:
                log.warning("Failed to record split: %s", exc)

        # Next split clock starts NOW
        self.split_start_time = now
        self.run_level_index += 1
        self.last_exit_time = now
        self.keyhole_latched = False
        # Track which level we just exited to prevent double-exit
        self.exited_level_id = previous.level_id
        self.active_level_deaths = 0

    # ── Level tracking ──

    def _emit_level_enter(self, state: HardwareGameState, game_name: str, now: float) -> None:
        if not state.is_smw or not self._is_playable_level_id(state.level_id):
            return
        if self.active_level_id == state.level_id:
            return
        if self.active_run and not self._is_level_in_run(state.level_id):
            log.debug("Level %s not in active run, skipping", state.level_id)
            return

        self.active_level_id = state.level_id
        self.active_level_name = state.level_name
        self.active_level_best_x = state.x_position
        self.active_level_deaths = 0
        self.keyhole_latched = False
        self.exited_level_id = None  # Clear exit guard — we're in a new level now

        if not self.run_started:
            delay_ms = self.active_run.get("start_delay_ms", 0) if self.active_run else 0
            self.split_start_time = now + (delay_ms / 1000.0)
            self.run_started = True
            self.run_level_index = 0
            self.client.post_event(
                event_type="run_start",
                game_name=game_name,
                level_id=None, level_name=None, x_position=None,
                details={
                    "start_epoch": now,
                    "delay_ms": delay_ms,
                    "timer_epoch": self.split_start_time,
                    "fallback": True,
                },
            )
            log.info("Run started on first level enter (fallback, delay=%dms)", delay_ms)

        self.client.post_event(
            event_type="level_enter", game_name=game_name,
            level_id=state.level_id, level_name=state.level_name,
            x_position=state.x_position,
            details={"entered_at": now, "game_mode": state.game_mode},
        )
        log.info("Level enter: %s (%s)", state.level_id, state.level_name)

    def _update_level_best_x(self, state: HardwareGameState) -> None:
        if not state.is_smw or state.x_position is None:
            return
        if self.active_level_best_x is None or state.x_position > self.active_level_best_x:
            self.active_level_best_x = state.x_position

    def _update_keyhole_latch(self, state: HardwareGameState) -> None:
        if state.keyhole_timer is not None and state.keyhole_timer > 0:
            self.keyhole_latched = True

    def _should_emit_progress(self, state: HardwareGameState, now: float) -> bool:
        if not state.is_smw:
            return now - self.last_progress_time >= 10.0
        if not self._is_playable_level_id(state.level_id):
            return False
        if self.last_state is None:
            return True
        if state.level_id != self.last_state.level_id:
            return True
        if state.x_position is None:
            return False
        if self.last_progress_x is None:
            return True
        if state.x_position >= self.last_progress_x + self.config.progress_threshold:
            return True
        if now - self.last_progress_time >= self.config.progress_interval_seconds:
            return True
        return False

    def _should_emit_death(self, state: HardwareGameState, now: float) -> bool:
        if not state.is_smw or self.last_state is None:
            return False
        if not self._is_playable_level_id(state.level_id):
            return False

        # Death cooldown: SMW death sequence takes ~3-4 seconds
        # (death anim → circle wipe → respawn). Use 3s cooldown to prevent
        # multiple signals from the same death being counted separately.
        DEATH_COOLDOWN = 3.0
        if (now - self.last_death_time) < DEATH_COOLDOWN:
            return False

        # Method 1: Lives counter decreased
        lives_dropped = (state.lives is not None and self.last_state.lives is not None
                         and state.lives < self.last_state.lives)

        # Method 2: Player animation trigger changed to death (0x09)
        # $7E:0071 — the authoritative death signal from SMWCentral RAM map.
        # Also check for 0x01 (dying bounce off screen — pit deaths, lava, etc).
        entered_death_anim = (state.player_anim_state in (ANIM_DEATH, ANIM_DYING_BOUNCE)
                              and self.last_state.player_anim_state not in (ANIM_DEATH, ANIM_DYING_BOUNCE))

        return lives_dropped or entered_death_anim

    # ── Main loop ──

    def process_once(self) -> HardwareGameState:
        state = self.read_state()
        now = time.time()

        # Load run config as soon as we see a real SMW game (any state)
        if state.is_smw and state.game_name:
            self._load_default_run(state.game_name)

        # Ensure session exists for SMW games so the UI shows "Now Playing"
        if state.is_smw and state.is_real_game and state.game_name:
            self._ensure_session(state.game_name)

        # Check for run auto-start BEFORE state machine update
        if state.is_smw and state.is_real_game:
            self._check_run_auto_start(state, now)

        self._update_runtime_state(state, now)

        if self.runtime_state != "playing":
            return state

        game_name = state.game_name or "Unknown Game"

        # IMPORTANT: Check exits BEFORE level enters
        # When level changes 03→0E in one poll, we need to exit 03 first,
        # then enter 0E. Otherwise entering 0E resets state that the exit needs.
        if self.last_state:
            should_exit, exit_type = self._should_emit_exit(state, now)
            if should_exit:
                self._emit_exit_and_split(self.last_state, state, game_name, exit_type, now)

        self._emit_level_enter(state, game_name, now)
        self._update_level_best_x(state)
        self._update_keyhole_latch(state)

        if self._should_emit_progress(state, now):
            self.client.post_progress(
                game_name=game_name, level_id=state.level_id,
                level_name=state.level_name, x_position=state.x_position,
            )
            self.last_progress_x = state.x_position
            self.last_progress_time = now

        if self._should_emit_death(state, now):
            self.active_level_deaths += 1
            self.client.post_event(
                event_type="death", game_name=game_name,
                level_id=state.level_id, level_name=state.level_name,
                x_position=state.x_position,
                details={"anim_state": state.player_anim_state, "lives": state.lives,
                         "best_x_before_death": self.active_level_best_x,
                         "level_deaths": self.active_level_deaths},
            )
            self.last_death_time = now
            self.last_death_at_wallclock = now

        self.last_state = state
        return state

    def run_forever(self, poll_seconds: float = 0.25) -> None:
        log.info("Starting SNES tracker loop (poll=%.2fs)...", poll_seconds)
        consecutive_errors = 0
        while True:
            try:
                self.process_once()
                consecutive_errors = 0
            except Exception as exc:
                consecutive_errors += 1
                exc_name = type(exc).__name__

                if consecutive_errors <= 2:
                    log.warning("Connection error (%d): %s: %s", consecutive_errors, exc_name, exc)
                else:
                    log.error("Connection error (%d): %s — reconnecting...", consecutive_errors, exc_name)
                    try:
                        self.qusb.reconnect()
                        self.qusb.auto_attach_first_device(wait=True, retry_seconds=2.0)
                        consecutive_errors = 0
                        log.info("Reconnected to QUsb2Snes")
                    except Exception as re:
                        log.error("Reconnection failed: %s", re)
                        time.sleep(self.config.reconnect_delay_seconds)
            time.sleep(poll_seconds)
