# config.py
import os

# Game settings
DEFAULT_PLAYER_COUNT = 6
# Role deck configuration: 9 cards for 6 players + 3 center cards
DECK_ROLES = ["Werewolf", "Werewolf", "Minion", "Seer", "Robber", "Troublemaker", "Mason", "Mason", "Drunk"]

# LLM parameters
DEFAULT_TEMP = 0.8
GEMINI_MODEL = "gemini-3.5-flash"

# Model thinking level: "OFF", "MINIMAL", "LOW", "MEDIUM", "HIGH"
DEFAULT_THINKING_LEVEL = "MEDIUM"

# Night action configuration: True to query LLMs, False to run programmatically (random choices)
# Disabled by default
LLM_DRIVEN_NIGHT_ACTIONS = False
