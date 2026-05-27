"""Keep pytest from collecting the research harness in this directory.

``test_signal.py`` is a manual research harness — its public entry point is the
function ``test_signal(signal_fn, ...)`` that measures a candidate signal's
per-trade R edge (see its module docstring). It is *not* a pytest test module,
but its name matches pytest's default collection patterns (``test_*.py`` and
``test_*`` functions), so pytest tries to run ``test_signal`` as a test and
errors looking for a ``signal_fn`` fixture. Exclude it from collection.
"""
collect_ignore = ["test_signal.py"]
