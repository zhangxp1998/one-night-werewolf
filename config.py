# config.py
import os

# Game settings
DEFAULT_PLAYER_COUNT = 6
# Role deck configuration: 9 cards for 6 players + 3 center cards
DECK_ROLES = ["Werewolf", "Werewolf", "Minion", "Seer", "Robber", "Troublemaker", "Mason", "Mason", "Drunk"]

# LLM parameters
DEFAULT_TEMP = 0.8
GEMINI_MODEL = "gemini-3.5-flash"  # You can adjust this to "gemini-2.0-flash" if needed

# Night action configuration: True to query LLMs, False to run programmatically (random choices)
LLM_DRIVEN_NIGHT_ACTIONS = True
