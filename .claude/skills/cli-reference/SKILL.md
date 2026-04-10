---
name: cli-reference
description: Reference for all agile-backlog CLI commands, flags, and usage patterns. Use when invoking agile-backlog commands to avoid guessing syntax.
---

# agile-backlog CLI Reference

Use this reference when running agile-backlog commands. Do NOT guess flags — use only the options documented here.

## Commands

### add — Create a new backlog item

```bash
agile-backlog add "TITLE" --category CATEGORY [OPTIONS]
```

| Flag | Required | Values | Default |
|------|----------|--------|---------|
| `--category` | yes | bug, feature, docs, chore | — |
| `--priority` | no | P0, P1, P2, P3, P4 | P2 |
| `--description` | no | string | "" |
| `--sprint` | no | integer | none |

### list — List backlog items with filters

```bash
agile-backlog list [OPTIONS]
```

| Flag | Values | Notes |
|------|--------|-------|
| `--status` | backlog, doing, done | |
| `--priority` | P0, P1, P2, P3, P4 | |
| `--category` | bug, feature, docs, chore | |
| `--sprint` | integer | filter by sprint number |
| `--tags` | string (repeatable) | items matching ANY tag shown |
| `--json` | flag | output as JSON |

### show — Show full details for an item

```bash
agile-backlog show ITEM_ID [--json]
```

### move — Change item status (accepts multiple IDs)

```bash
agile-backlog move ID [ID...] --status STATUS [OPTIONS]
```

| Flag | Required | Values |
|------|----------|--------|
| `--status` | yes | backlog, doing, done |
| `--phase` | no | plan, spec, build, review |
| `--sprint` | no | integer (set sprint target) |

**Important:** Use `move` to change status, NOT `edit --status`.

### edit — Edit fields on an item (accepts multiple IDs)

```bash
agile-backlog edit ID [ID...] [OPTIONS]
```

| Flag | Values | Notes |
|------|--------|-------|
| `--title` | string | |
| `--priority` | P0-P4 | |
| `--category` | bug, feature, docs, chore | |
| `--description` | string | |
| `--sprint` | integer | sprint target |
| `--goal` | string | |
| `--complexity` | S, M, L | |
| `--technical-specs` | string (repeatable) | |
| `--acceptance-criteria` | string (repeatable) | |
| `--test-plan` | string (repeatable) | |
| `--phase` | plan, spec, build, review | |
| `--tags` | string (repeatable) | |
| `--depends-on` | string (repeatable) | |
| `--notes` | string | |
| `--design-reviewed` | flag | |
| `--code-reviewed` | flag | |
| `--resolve-notes` | flag | mark all flagged notes resolved |

### note — Add a note to an item

```bash
agile-backlog note ITEM_ID "TEXT" [--flag]
```

`--flag` marks the note for agent attention (shows in `flagged` output).

### flagged — List items with unresolved flagged notes

```bash
agile-backlog flagged [--json]
```

### resolve-note — Resolve a note by index

```bash
agile-backlog resolve-note ITEM_ID NOTE_INDEX
```

Note index is 0-based.

### sprint-status — Show current sprint items by phase

```bash
agile-backlog sprint-status [--sprint N]
```

Defaults to current sprint from config. Shows items grouped by phase with progress count.

### validate — Check sprint items have required spec fields

```bash
agile-backlog validate [--sprint N]
```

Checks: goal, complexity, >=2 acceptance criteria, >=1 technical spec. Exit code 1 on failure.

### set-sprint — Set the current sprint number

```bash
agile-backlog set-sprint NUMBER
```

### serve — Open the web UI

```bash
agile-backlog serve [--port 8501] [--host 127.0.0.1] [--reload]
```

### stop / restart — Server management

```bash
agile-backlog stop
agile-backlog restart [--port 8501] [--host 127.0.0.1] [--reload]
```

## Common Patterns

```bash
# Create and spec an item
agile-backlog add "Fix auth bug" --category bug --priority P1
agile-backlog edit fix-auth-bug --goal "Fix the auth bug" --complexity S \
  --acceptance-criteria "Auth works" --acceptance-criteria "Tests pass" \
  --technical-specs "File: src/auth.py"

# Move to sprint and start work
agile-backlog move fix-auth-bug --status doing --phase build --sprint 5

# Bulk operations
agile-backlog move item-a item-b item-c --status done
agile-backlog edit item-a item-b --sprint 5

# Check sprint progress
agile-backlog sprint-status
agile-backlog validate
```
