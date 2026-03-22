from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryField:
    name: str
    address: int
    size: int


# QUsb2Snes mapped addresses (WRAM $7E:xxxx -> 0xF5xxxx)
LEVEL_ID = MemoryField("level_id", 0xF513BF, 1)
PLAYER_X = MemoryField("player_x", 0xF50094, 2)
PLAYER_ANIM_STATE = MemoryField("player_anim_state", 0xF50071, 1)
LIVES = MemoryField("lives", 0xF50DBE, 1)
EXIT_STATE = MemoryField("exit_state", 0xF51493, 1)
KEYHOLE_TIMER = MemoryField("keyhole_timer", 0xF51434, 1)

# Game mode: controls what phase the game is in
# 0x06 = title/file select, 0x0C = OW loading, 0x0D = OW active,
# 0x0E = fade to level, 0x14 = in level gameplay
GAME_MODE = MemoryField("game_mode", 0xF50100, 1)

ALL_FIELDS = [LEVEL_ID, PLAYER_X, PLAYER_ANIM_STATE, LIVES, EXIT_STATE, KEYHOLE_TIMER, GAME_MODE]

# Game mode constants
GM_TITLE_SCREEN = 0x06
GM_OVERWORLD_LOAD = 0x0C
GM_OVERWORLD = 0x0D
GM_FADE_TO_LEVEL = 0x0E
GM_LEVEL_LOAD = 0x0F
GM_IN_LEVEL = 0x14
