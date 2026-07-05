---
name: polish-diss-lesson-generator
description: Generates daily Polish language lessons using the DiSSS Functional Context method, following strict pedagogical and formatting requirements.
---

# Polish DiSSS Lesson Generation

This skill provides the framework for generating structured Polish language lessons based on the "DiSSS Functional Context" approach.

## Trigger
- User requests a daily Polish lesson.
- Scheduled cron jobs for language acquisition.

## Pedagogical Structure (DiSSS Method)
Each lesson must contain:
1. **Vocabulary**: 10 words from the top 500 most common Polish words.
2. **n+1 Sentence Mining**: 10 sentences using the new vocabulary, designed for "comprehensible input" (introducing one new element at a time).
3. **Grammar - Verb Aspects**: Explicitly showing aspect pairs (Perfective vs. Imperfective).
4. **Grammar - Noun Cases**: Showing declension patterns for the key nouns in the lesson.
5. **Lückentext-Quiz (Gap-fill)**: 10 questions testing the vocabulary and grammar.
6. **Answer Key**: A complete list of solutions at the end.

## Formatting Rules
- **Polish**: Always use `**bold**` (e.g., **dom**).
- **German**: Always use `` `monospace` `` (e.g., `Haus`).
- **Sentence Mining**: Use `**Polish**` `German` format.

## Workflow
1. **Determine Progress**: Read the existing log file (e.g., `~/obsidian-vault/Lernen/Polnisch/04-Tagebuch.md`) to identify the last completed lesson number.
2. **Deduplication**: Parse the log file to identify previously used words to ensure no repetition.
3. **Content Generation**: Construct the lesson following the structure and formatting rules above.
4. **Logging**: Append the full lesson to the diary file.
5. **Completion**: End the lesson with the exact string: `Lektion #X abgeschlossen.`

## Pitfalls
- **Missing Skills**: The specialized `polnisch-disss-context` skill may be missing. If so, fallback to manual implementation of this structure.
- **Redundancy**: Failing to check the diary file for previous words violates the core instruction.
- **Formatting Errors**: Mixing up bold/monospace for Polish/German makes the lesson unreadable for the user.

## References
- `references/lesson-structure-example.md`: A template of a correctly formatted lesson.
