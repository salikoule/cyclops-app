"""Cached choice lists and the signed-in user's access."""

import anvil.server

_CHOICES = None
_SESSION = None


def choices():
    global _CHOICES
    if _CHOICES is None:
        _CHOICES = anvil.server.call("cyclops_choices")
    return _CHOICES


def invalidate():
    global _CHOICES
    _CHOICES = None


def session(force=False):
    global _SESSION
    if _SESSION is None or force:
        _SESSION = anvil.server.call("cyclops_session") or {}
    return _SESSION


def invalidate_session():
    global _SESSION
    _SESSION = None


def can_write():
    return bool(session().get("canWrite"))
