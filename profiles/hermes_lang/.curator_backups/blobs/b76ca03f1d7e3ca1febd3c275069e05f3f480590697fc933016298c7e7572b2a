---
name: automated-language-lesson-generator
description: "Automates the generation of language lessons using the DiSSS framework and logs them into Obsidian diaries."
tags: [language-learning, automation, obsidian, diss, cron]
---

# Automated Language Lesson Generation

This skill provides a workflow for automating the creation of structured language lessons (e.g., Polish) and appending them to a persistent diary in an Obsidian vault.

## Core Workflow

1.  **State Recovery**: 
    - Read the existing diary file (e.g., `~/obsidian-vault/Lernen/<Language>/<Path>.md`).
    - Parse the content to find the highest `Lektion #X` to determine the next lesson number.
    - Extract a list of previously used vocabulary to ensure uniqueness.
2.  **Content Generation (DiSSS Framework)**:
    - **Vocabulary**: Select 10 words from a high-frequency list (e.g., Top 500).
    - **n+1 Sentence Mining**: Create 10 sentences combining new words with known structures.
    - **Grammar Focus**: Select a grammatical concept (e.g., Verb Aspects, Noun Case).
    - **Interactive Quiz**: Generate 10 gap-fill (Lückentext) questions.
    - **Solutions**: Provide an answer key at the end.
3.  **Formatting (Strict)**:
    - **Target Language**: **bold** (e.g., `**pies**`).
    - `Translation/Second Language`: `monospace` (e.g., `` `Hund` ``).
4.  **Logging**:
    - Append the new lesson to the diary file.
    - End with `Lektion #X abgeschlossen.`
5.  **Cron Delivery**:
    - Output the lesson directly as the final response.
    - Use `[SILENT]` if no update is needed.

## Implementation Pitfalls

- **Duplication**: Failing to deduplicate vocabulary against the existing diary history.
- **Formatting Mixups**: Swapping bold and monospace between the target and second language.
- **Delivery Errors**: Attempting to use `send_message` in a cron environment instead of direct output.
- **File Parsing**: Failing to handle Markdown formatting or line numbering when reading the diary.

## Templates and References
- See `references/polish-implementation.md` for language-specific pedagogical rules.
