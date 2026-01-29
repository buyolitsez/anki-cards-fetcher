# Cambridge / Wiktionary Fetcher

Tags: dictionary, Cambridge, Wiktionary, audio, image, examples, synonyms, flashcards, English, Russian, note-creator

## Overview
Fetch definitions into Anki from either Cambridge Dictionary (English) or ru.wiktionary.org (Russian). The add-on maps definition, examples, synonyms, audio (Cambridge only), and picture (Cambridge only) into your note fields.

## How to Use
1) Open **Tools → Dictionary Fetch (Cambridge/Wiktionary)** (hotkey `Ctrl+Shift+C`).  
2) Enter a word, choose **Source** (Cambridge / Wiktionary), press **Fetch**.  
3) Pick a sense from the list; preview shows what will be inserted.  
4) Click **Insert** (or double-click a sense) to add the note; **Insert & Edit** opens it in the Browser.

## Settings
Open **Tools → Dictionary Fetch — Settings**. Configure:
- Default note type and deck.
- Remember last selections.
- Default source.
- Audio dialect priority for Cambridge (UK>US or US>UK).
- Field mapping: for each logical field (word, definition, examples, synonyms, audio, picture) list one or more Anki fields, comma-separated (e.g., `Word, Front` or `Examples, Example`).

## Implementation Notes
- Uses `requests` + `BeautifulSoup`. Cambridge parser gathers audio from multiple attributes/buttons (including AMP) and images from `/media/` links. Wiktionary parser reads the “Значение”/“Синонимы” sections inside the Russian language block.
- Field mapping (`config.json` / addon config) keys: `word`, `definition`, `examples`, `synonyms`, `audio`, `picture`.
- Media files are downloaded into Anki’s collection; audio is inserted as `[sound:filename]`, images as `<img src="filename">`.
