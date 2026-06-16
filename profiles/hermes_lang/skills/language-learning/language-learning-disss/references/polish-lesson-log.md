# Polish DiSSS Implementation Log

This reference file tracks the automated generation of Polish DiSSS lessons to ensure vocabulary uniqueness and lesson continuity.

## Lesson Generation Metadata

### Lesson #18 (June 12, 2026)
- **Vocab Focus**: being, having, doing, speaking, going, seeing, knowing, wanting, eating, drinking.
- **Grammar**: Verb aspects (robić/zrobić), Noun cases (woda/wodę, dom/dom).

### Lesson #19
- **Vocab Focus**: year, human, evening, book, eye, table, door, leg, word, question.
- **Grammar**: Verb aspects (pisać/napisać, brać/wziąć), Noun cases (rok/roku, książka/książkę).

### Lesson #20
- **Vocab Focus**: now, very, here, always, still, only, when, much, maybe, nothing.
- **Grammar**: Verb aspects (kupować/kupić, szukać/znaleźć), Noun cases (kawa/kawę, praca/pracy).

## Automated Workflow Notes
- **Progress Tracking**: Path `~/obsidian-vault/Lernen/Polnisch/04-Tagebuch.md`.
- **Formatting Standard**: Polish words in **bold**, German translations in `monospace`.
- **Lesson Logic**: Always increment lesson number by reading the last entry in the diary.
- **Vocabulary Constraint**: Always verify against previous lessons to prevent repetition.
