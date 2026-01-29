# Cambridge Fetcher

Tags: dictionary, Cambridge, lookup, audio, image, examples, synonyms, flashcards, English, note-creator

## Overview
Cambridge Fetcher adds a toolbar button and shortcut (Ctrl+Shift+C) to create a new note from dictionary.cambridge.org with one click. It pulls definition, examples, synonyms, audio (UK/US order is configurable), and an image, then maps them into your Anki fields and deck.

## How to Use
1) Click the “Tools → Cambridge Fetch” button on the top toolbar (or use Ctrl+Shift+C).  
2) Type a word and press “Fetch”.  
3) Choose the desired sense; preview shows definition, examples, synonyms, audio availability, and picture flag.  
4) Press “Insert” (or double-click) to create the note; “Insert & Edit” opens it in the browser.  
5) Settings: Add-ons → Cambridge Fetch → Config. Pick default note type, deck, whether to remember the last choice, and set audio dialect priority (UK > US or US > UK).

## Implementation Notes
- **Fetching and parsing**: Uses `requests` and `BeautifulSoup`. For each `div.entry`, it collects audio links from `data-src-mp3/ogg`, `source[src]`, `audio[src]`, and Cambridge media links; regions are inferred from nearby `.region/.dregion` text or CSS classes. Examples are gathered from `.examp`, `.dexamp`, `span.eg/deg`, and related selectors; synonyms from thesaurus and accordian blocks. Images come from `img/srcset/src` or `amp-img` pointing to `/media/` files.
- **Field mapping**: `field_map` in config maps logical keys (`word`, `definition`, `examples`, `synonyms`, `audio`, `picture`) to your model fields. During insertion, the note is created with the chosen model/deck, then each mapped field is set. Audio and pictures are downloaded into the media collection; audio is inserted as `[sound:...]`, images as `<img src="...">`.


