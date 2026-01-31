# Tests

These tests are designed to run outside Anki and avoid network calls by using local HTML snapshots.

## Where to run from
Run commands from the add-on root folder:

```
/Users/Nikolay.Chukhin/Library/Application Support/Anki2/addons21/cambridge_fetch
```

## Install test deps
If tests are skipped with `importorskip`, install the missing packages:

```
python3 -m pip install pytest beautifulsoup4
```

## Run

```
python3 -m pytest -q
```

## Snapshot tests (real pages)
Snapshots live in `tests/snapshots/`. If they are missing or outdated, refresh them (requires network):

```
python3 tests/update_snapshots.py
```

Then run tests again.
