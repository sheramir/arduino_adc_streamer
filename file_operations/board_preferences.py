"""Persist board/mode preferences using the application's shared JSON helpers."""
from pathlib import Path
from config.boards.settings import BoardPreferences, context_for
from file_operations.settings_persistence import load_settings_payload, save_settings_payload


def preferences_path():
    return Path.home() / '.adc_streamer' / 'last_used_board_settings.json'


def load_board_preferences(owner):
    try:
        _, payload = load_settings_payload(preferences_path())
        if not isinstance(payload, dict) or payload.get('version') != 1 or not isinstance(payload.get('boards'), dict):
            raise ValueError('Unsupported board preferences')
        owner.board_preferences = BoardPreferences(payload['boards'])
    except FileNotFoundError:
        owner.board_preferences = BoardPreferences()
    except (ValueError, TypeError):
        owner.board_preferences = BoardPreferences()
        owner.log_status('Ignoring invalid saved board preferences')


def save_board_preferences(owner):
    if not hasattr(owner, 'config'):
        return
    preferences = getattr(owner, 'board_preferences', BoardPreferences())
    try:
        preferences.save(context_for(owner), owner.config)
        save_settings_payload(preferences_path(), {'version': 1, 'boards': preferences.data})
    except (OSError, ValueError) as exc:
        owner.log_status(f'Could not save board preferences: {exc}')
