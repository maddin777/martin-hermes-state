---
name: language-learning-disss
description: "Comprehensive workflow for language acquisition using the DiSSS (Deconstruction, Selection, Sequencing, Stakes) framework."
tags: [language-learning, diss, methodology, acquisition]
---

# Language Learning with DiSSS

This umbrella skill provides the framework for rapid language acquisition using the DiSSS methodology. It is designed to be applied to any language, though specific implementations (like Polish) are stored in the `references/` directory.

## Methodology: DiSSS Framework

1.  **Deconstruction**: Breaking the language into its most high-leverage components (high-frequency vocabulary, core grammar patterns).
2.  **Selection**: Prioritizing the "Top 500" words and essential grammatical structures that yield the highest ROI.
3.  **Sequencing**: Organizing content into logical, incremental daily lessons.
4.  **Stakes/Application**: Using n+1 sentence mining and active retrieval (gap-fill quizzes) to ensure retention.

## Implementation Workflow

### Step 1: Deconstruction & Selection
Identify the high-frequency core of the target language. Use existing knowledge banks or research to define the "Top 500" vocabulary and essential grammar (aspects, cases, etc.).

### Step 2: Sequence Generation
Create a syllabus that organizes the selected content into daily, manageable lessons.

### Step 3: Lesson Production
Every lesson MUST follow a strict structure to ensure cognitive load is optimized:
1.  **Vocabulary (Top 500)**: 10 high-frequency words.
2.  **n+1 Sentence Mining**: Contextual sentences using new vocabulary + previously learned structures.
3.  **Grammar Focus**: One specific grammatical hook (e.g., verb aspect, noun case).
4.  **Interactive Quiz**: 10 fill-in-the-blank sentences (Lueckentext).
5.  **Answer Key**: A clear solution key at the end.

## Automation & Tracking

- **Progress Tracking**: Use Obsidian (or similar) to maintain a daily log and determine the next lesson number.
- **Cron-Job Integration**: This workflow is designed to be executed autonomously via scheduled tasks.

## References & Specialized Workflows

Specific implementations of this framework can be found in the references directory.

- `references/polish-disss-implementation.md`: Detailed implementation for Polish language learning.
