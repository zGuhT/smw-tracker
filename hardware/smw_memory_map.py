"""
SMW Memory Map — RAM addresses for tracker state detection.

All addresses are QUsb2Snes mapped: WRAM $7E:xxxx -> 0xF5xxxx.
Reference: https://www.smwcentral.net/?p=memorymap&game=smw&region=ram

Game Mode ($7E:0100) values:
  00    Load Nintendo Presents
  01    Nintendo Presents
  02    Fade to Title Screen
  03    Load Title Screen
  04    Prepare Title Screen
  05    Title Screen: Fade in
  06    Title Screen: Circle effect
  07    Title Screen
  08    Title Screen: File select
  09    Title Screen: File delete
  0A    Title Screen: Player select
  0B    Fade to Overworld
  0C    Load Overworld
  0D    Overworld: Fade in
  0E    Overworld
  0F    Fade to Level (triggered by door/pipe — mosaic effect)
  10    Fade to Level (black)
  11    Load Level ("Mario Start!")
  12    Prepare Level (death sequence also uses this)
  13    Level: Fade in
  14    Level (normal gameplay)
  15    Fade to Game Over
  16    Fade to Game Over (continued)
  17    Game Over screen
  18-29 Credits / ending sequence

Player Animation Trigger ($7E:0071) values:
  00    Normal / idle
  01    Dying (bouncing up off screen)
  02    Get Mushroom / grow animation
  03    Get Cape / Fire Flower animation
  04    Shooting fireball
  05    Spring board bounce
  06    Entering/exiting pipe
  07    Star invincibility sparkle
  08    Shrink from hit (lose powerup)
  09    Death animation (hit by enemy / fall in pit)
  0A    Castle entrance
  0B    Goal walk
  0C    Getting thrown / Yoshi wings
  0D    P-Balloon inflation

Door/Pipe transitions:
  When entering a door or pipe, game_mode goes 14 -> 0F -> 10 -> 11 -> 12 -> 13 -> 14.
  The translevel_number ($13BF) stays the SAME across door transitions within one level.
  The sublevel_number (room number from level data) changes but 13BF does not.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryField:
    name: str
    address: int
    size: int


# ── Core tracking addresses ──

# Translevel number — identifies which overworld level this room belongs to.
# Stays the same across door/pipe transitions within the same level.
# To convert to room number: if > 0x24, add 0xDC.
LEVEL_ID = MemoryField("level_id", 0xF513BF, 1)

# Player X position within the level (16-bit), one frame ahead.
PLAYER_X = MemoryField("player_x", 0xF50094, 2)

# Player animation trigger — controls what animation is playing.
# 0x00=idle, 0x01=dying(bounce), 0x06=pipe, 0x09=death, 0x0B=goal walk
PLAYER_ANIM_STATE = MemoryField("player_anim_state", 0xF50071, 1)

# Lives counter (0-based: 0 = 1 life displayed, 0xFF = wraps from 0)
LIVES = MemoryField("lives", 0xF50DBE, 1)

# End level timer — set to non-zero when goal tape / orb is touched.
# Counts down; level ends when it reaches 0. Also called "goal tape timer".
EXIT_STATE = MemoryField("exit_state", 0xF51493, 1)

# Keyhole timer — goes non-zero when a key enters a keyhole (secret exit).
KEYHOLE_TIMER = MemoryField("keyhole_timer", 0xF51434, 1)

# Game mode — controls what phase the game is in.
# See docstring above for complete value list.
GAME_MODE = MemoryField("game_mode", 0xF50100, 1)

# ── Additional useful addresses ──

# Lock animation flag — non-zero during death, powerup grab, keyhole, etc.
# When set, sprites freeze and animation plays out.
LOCK_ANIM_FLAG = MemoryField("lock_anim_flag", 0xF5009D, 1)

# Player powerup status: 0x00=small, 0x01=big, 0x02=cape, 0x03=fire
PLAYER_POWERUP = MemoryField("player_powerup", 0xF50019, 1)

# Player Y speed: 0x00-0x7F = falling, 0x80-0xFF = rising
# Max fall = 0x46, normal jump = 0xB3, full run jump = 0xA4
PLAYER_Y_SPEED = MemoryField("player_y_speed", 0xF5007D, 1)

# Player is in water flag: 0x00 = no, 0x01 = yes
PLAYER_IN_WATER = MemoryField("player_in_water", 0xF50075, 1)

# Yoshi: 0x00 = not riding, non-zero = riding Yoshi
ON_YOSHI = MemoryField("on_yoshi", 0xF5187A, 1)

# Level passed flag — set by various end-of-level routines
LEVEL_PASSED = MemoryField("level_passed", 0xF50DD5, 1)

# Player Y position within level (16-bit)
PLAYER_Y = MemoryField("player_y", 0xF50096, 2)


# Fields read on every poll cycle (keep minimal for speed)
ALL_FIELDS = [
    LEVEL_ID, PLAYER_X, PLAYER_ANIM_STATE, LIVES,
    EXIT_STATE, KEYHOLE_TIMER, GAME_MODE,
]

# Extended fields (read less frequently for stats/detail)
EXTENDED_FIELDS = [
    LOCK_ANIM_FLAG, PLAYER_POWERUP, PLAYER_Y_SPEED,
    PLAYER_IN_WATER, ON_YOSHI, LEVEL_PASSED, PLAYER_Y,
]


# ── Game mode classification (for tracker state machine) ──
# NOTE: These groupings are for the TRACKER's state machine, not strict SMW terminology.
# The tracker needs broad "in game" vs "menu" classification.

# Menu/title/loading modes (not in gameplay)
MENU_MODES = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A}

# "In game" modes — everything from overworld through level gameplay.
# The tracker treats all of these as "game is running" for state machine purposes.
# Includes: overworld (0B-0E), level transitions (0F-13), active gameplay (14)
GAMEPLAY_MODES = {0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x14}

# Level end / game over modes
LEVEL_END_MODES = {0x15, 0x16, 0x17}

# Strictly "in a level playing" — game mode 0x14 only.
# Used for exit detection Method 4 (level ID change must happen during actual gameplay)
LEVEL_GAMEPLAY_ONLY = {0x14}

# Level transition modes (door/pipe: 0F->10->11->12->13->14)
LEVEL_TRANSITION_MODES = {0x0F, 0x10, 0x11, 0x12, 0x13}

# Overworld modes
OVERWORLD_MODES = {0x0B, 0x0C, 0x0D, 0x0E}

# All "in level" modes (for tracker to stay active)
IN_LEVEL_MODES = LEVEL_TRANSITION_MODES | LEVEL_GAMEPLAY_ONLY


# ── Player animation constants ──

ANIM_IDLE = 0x00
ANIM_DYING_BOUNCE = 0x01    # Dying — bouncing up off screen
ANIM_GET_MUSHROOM = 0x02
ANIM_GET_CAPE = 0x03
ANIM_FIREBALL = 0x04
ANIM_SPRINGBOARD = 0x05
ANIM_PIPE = 0x06            # Entering/exiting pipe
ANIM_STAR = 0x07
ANIM_SHRINK = 0x08          # Lose powerup (hit while big)
ANIM_DEATH = 0x09           # Standard death animation
ANIM_CASTLE_ENTER = 0x0A
ANIM_GOAL_WALK = 0x0B       # Walking through goal
ANIM_YOSHI_WINGS = 0x0C
ANIM_P_BALLOON = 0x0D
