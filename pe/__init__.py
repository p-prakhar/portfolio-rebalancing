import warnings

# yfinance still uses pandas calls that pandas 3.x deprecates, and re-enables those warnings when it is imported,
# so import it first and filter afterwards. Harmless, but they flood the terminal.
try:
    import yfinance  # noqa: F401
except Exception:
    pass
warnings.filterwarnings("ignore", module=r"yfinance(\..*)?")


import contextlib


@contextlib.contextmanager
def quiet():
    """Suppress all warnings inside a network/library call, whatever filters the library installed."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield
