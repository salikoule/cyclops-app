import anvil.tables as tables
import anvil.tables.query as q
from anvil.tables import app_tables
"""Cached choice lists for the editors."""

import anvil.server

_CHOICES = None


def choices():
    global _CHOICES
    if _CHOICES is None:
        _CHOICES = anvil.server.call("cyclops_choices")
    return _CHOICES


def invalidate():
    global _CHOICES
    _CHOICES = None
