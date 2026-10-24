import warnings

# yfinance still uses pandas calls that pandas 3.x deprecates; harmless, and they flood the terminal.
warnings.filterwarnings("ignore", module=r"yfinance(\..*)?")
