---
name: document
description: Documentation skill with 7 modes — research, design, architecture, audit, runbook, update, and review.
---

# Document Skill

You are running a documentation process. The user invoked `/document $ARGUMENTS`.

## Prerequisites

**Read `.claude/sprint-config.yaml`** to get project-specific commands. All commands below use config references like `{ci_command}`, `{backlog_commands.list}`, etc. — substitute with actual values from the config.

Parse the first word of `$ARGUMENTS` to determine the mode: `research`, `design`, `architecture`, `audit`, `runbook`, `update`, or `review`. Remaining words are the topic/file argument.

---

## Mode: `/document research [topic]` — Options Analysis

Research a topic and produce a structured options analysis document.

### Steps

1. Clarify the topic and decision to be made with the user
2. Research the codebase for existing related patterns and decisions
3. Search for prior specs or plans in `{docs.specs_dir}` and `{docs.plans_dir}`
4. Produce an **Options Analysis** document:
   - **Context** — why this decision matters now
   - **Options** — 2-4 alternatives, each with pros/cons/effort
   - **Recommendation** — which option and why
   - **Decision criteria** — what factors matter most
   - **Next steps** — what to do after deciding
5. Save to `{docs.specs_dir}` with date prefix: `YYYY-MM-DD-research-{topic}.md`

---

## Mode: `/document design [feature]` — Design Document

Write a formal design document after decisions have been made (use `superpowers:brainstorming` first for interactive design exploration).

### Steps

1. Ask the user for the feature name and any prior brainstorming/research docs
2. Read related specs from `{docs.specs_dir}` and plans from `{docs.plans_dir}`
3. Explore the codebase for integration points
4. Produce a **Design Document**:
   - **Overview** — what and why
   - **Design decisions** — key choices with rationale
   - **Architecture** — components, data flow, interfaces
   - **API/Interface changes** — public surface area affected
   - **Data model changes** — schema or file format changes
   - **Migration plan** — if applicable
   - **Testing strategy** — how to verify the design works
   - **Open questions** — anything unresolved
5. Save to `{docs.specs_dir}` with date prefix: `YYYY-MM-DD-design-{feature}.md`

---

## Mode: `/document architecture` — System Overview

Generate a system architecture overview from the actual codebase.

### Steps

1. Scan the project structure — directories, modules, entry points
2. Read `CLAUDE.md` for project conventions and dependencies
3. Read `{docs.project_context}` for existing context
4. Analyze:
   - Module dependency graph (imports)
   - Entry points (CLI, web UI, API)
   - Data flow (how data moves through the system)
   - External dependencies
5. Produce an **Architecture Overview**:
   - **System diagram** — text-based component diagram
   - **Module inventory** — each module's purpose and key files
   - **Data flow** — how information moves through the system
   - **Dependencies** — external packages and their roles
   - **Extension points** — where new features plug in
6. Save to `{docs.specs_dir}` with date prefix: `YYYY-MM-DD-architecture-overview.md`

---

## Mode: `/document audit` — Staleness Audit

Audit all documentation for staleness and accuracy.

### Steps

1. Find all markdown docs:

```bash
find docs/ -name "*.md" -type f | sort
```

2. For each document:
   - Check last modified date vs related code files
   - Verify referenced file paths still exist
   - Check referenced commands still work
   - Flag outdated version numbers or tool references

3. Produce a **Staleness Report**:
   - **Up to date** — docs that match current code
   - **Possibly stale** — docs older than related code changes
   - **Definitely stale** — docs referencing missing files/commands
   - **Missing docs** — code modules with no documentation
4. Present the report. Ask user which items to fix.

---

## Mode: `/document runbook [op]` — Operational Runbook

Create an operational runbook for a specific operation.

### Steps

1. Clarify the operation (deploy, release, incident response, etc.)
2. Explore the codebase for related scripts, configs, and commands
3. Produce a **Runbook**:
   - **Purpose** — when to use this runbook
   - **Prerequisites** — tools, access, environment needed
   - **Steps** — numbered, copy-pasteable commands
   - **Verification** — how to confirm each step succeeded
   - **Rollback** — how to undo if something goes wrong
   - **Troubleshooting** — common issues and fixes
4. Save to `docs/runbooks/` (create directory if needed)

---

## Mode: `/document update [file]` — Refresh Document

Update an existing document to match current code.

### Steps

1. Read the specified file
2. Identify all code references (file paths, function names, commands)
3. Verify each reference against the current codebase
4. Update outdated references, examples, and descriptions
5. Mark any sections that need human review with `<!-- TODO: verify -->`
6. Present a diff summary of changes made

---

## Mode: `/document review [file]` — Review Document

Review a document for completeness and quality.

### Steps

1. Read the specified file
2. Evaluate against checklist:
   - **Purpose** — is the document's goal clear?
   - **Audience** — is the target reader defined?
   - **Accuracy** — do code references match reality?
   - **Completeness** — are there gaps or missing sections?
   - **Clarity** — is the writing clear and concise?
   - **Actionability** — can the reader act on this?
   - **Freshness** — is the content current?
3. Produce a **Review Report** with findings and suggestions
4. Ask user if they want to apply suggested fixes

## Important Rules

- Always verify code references against the actual codebase
- Use `{docs.specs_dir}` and `{docs.plans_dir}` for saving new documents
- Date-prefix all new documents: `YYYY-MM-DD-{slug}.md`
- Do not create documents the user did not ask for
