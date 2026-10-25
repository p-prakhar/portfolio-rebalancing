# End-to-end check

Run from the project folder. Every command is read-only for your money: nothing places orders.

```bash
cd ~/portfolio-rebalancing/portfolio-engine
git checkout main && git pull origin main      # get the latest code
source .venv/bin/activate
pip install -r requirements.txt                 # only needed after updates
python -m pytest -q tests                       # unit tests, about 10 seconds, should say "passed"
```

## 1. Your data (in the shell)

```bash
python main.py            # opens the shell; type `next` to see what is missing
```

Inside the shell: `setup` walks through profile, income and imports. Then `status`, `fds` and `mf` should show what you loaded.

## 2. Today's decision

```bash
python main.py run        # text plan, also saved to reports/latest.md
python main.py site --open   # the visual page, reports/index.html
```

On the page, click through all seven tabs. The Plan tab's slider should change the orders, and the Track record dots should open a decision.

## 3. Research runs (slower, needs internet)

| command | about how long | writes |
|---|---|---|
| `python main.py compare` | 1 min | reports/universe.md |
| `python main.py crash` | under 1 min | crash guard reading for today |
| `python main.py validate` | 3 to 5 min | reports/validation.md |
| `python main.py simulate-daily` | 1 to 2 min | reports/daily_sim.md |
| `python main.py simulate-daily --all-strategies` | 3 min | reports/daily_sim_all.md |
| `python main.py switch` | under 1 min | reports/switcher.md (needs the run above) |
| `python main.py timing` | a few min | reports/timing.md |
| `python main.py forecast` | a few min | reports/forecast.md |
| `python main.py crash-test` | 1 min | reports/crash_test.md |

Then rebuild the page (`python main.py site`) so it includes the new results.

A command that fails prints one line; the shell keeps details in state/shell_errors.log.
