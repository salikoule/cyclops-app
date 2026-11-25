import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "client_code" / "ui" / "duration.py"
_spec = importlib.util.spec_from_file_location("duration", _path)
duration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(duration)


def test_hours_and_minutes():
    assert duration.text(5.5) == "5h 30min"
    assert duration.text(0.75) == "45 min"
    assert duration.text(8) == "8h"
    assert duration.text(1 / 60) == "1 min"
    assert duration.text(0) == "0 min"


def test_run_list_can_filter_by_shift():
    import listing

    assert "shift" in listing.LISTS["run"]["filter"]
    assert hasattr(listing.LISTS["run"]["filter"]["shift"], "choices")
