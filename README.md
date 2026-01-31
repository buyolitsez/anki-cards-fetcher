# Cambridge / Wiktionary Fetcher

Tags: dictionary, Cambridge, Wiktionary, audio, image, examples, synonyms, flashcards, English, Russian, note-creator

## Overview
Fetch definitions into Anki from Cambridge Dictionary (English), ru.wiktionary.org (Russian), or en.wiktionary.org (English). The add-on maps definition, examples, synonyms, part of speech, IPA, audio, syllables/stress (RU Wiktionary), and pictures into your note fields.

## How to Use
1) Open **Tools → Dictionary Fetch (Cambridge/Wiktionary)** (hotkey `Ctrl+Shift+C`).  
2) Enter a word, choose **Source** (Cambridge / Wiktionary), press **Fetch**.  
3) Pick a sense from the list; preview shows what will be inserted.  
4) Optional: click **Find Image** to search images for the current word and pick one.
5) Click **Insert** (or double-click a sense) to add the note; **Insert & Edit** opens it in the Browser.

## Settings
Open **Tools → Dictionary Fetch — Settings**. Configure:
- Default note type and deck.
- Remember last selections.
- Default source.
- Audio/IPA dialect priority for Cambridge (UK>US or US>UK).
- Image search provider and result count (used by **Find Image**).
- Field mapping: for each logical field (word, definition, examples, synonyms, POS, IPA, audio, picture) list one or more Anki fields, comma-separated (e.g., `Word, Front` or `Examples, Example`).

## Implementation Notes
- Uses `requests` + `BeautifulSoup`. Cambridge parser gathers audio from multiple attributes/buttons (including AMP) and images from `/media/` links. Wiktionary RU parser reads the “Значение”/“Синонимы” sections; Wiktionary EN parser reads the English language block with POS headings, definitions, examples, synonyms, pronunciation (IPA/audio), and images.
- Field mapping (`config.json` / addon config) keys: `word`, `definition`, `examples`, `synonyms`, `pos`, `ipa`, `audio`, `picture`. Wiktionary RU-only mapping lives under `wiktionary.field_map` (e.g., `syllables`).
- Media files are downloaded into Anki’s collection; audio is inserted as `[sound:filename]`, images as `<img src="filename">`.
