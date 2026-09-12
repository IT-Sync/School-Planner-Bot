# Codex repository instructions

These rules apply to the whole repository.

## Persistent project memory

- `PROJECT_MEMORY.md` is the primary authoritative snapshot of the current project.
- `ARCHITECTURE.md` is the authoritative reference for architecture, data flow, infrastructure, integrations, and deployment topology.
- `TODO.md` is the authoritative tracker for unfinished work, known bugs, and technical debt.
- Always read `PROJECT_MEMORY.md` before substantial work.
- Read `TODO.md` when work concerns current priorities, bugs, or unfinished work.
- Read `ARCHITECTURE.md` before changing architecture, infrastructure, integrations, deployment, APIs, storage, authentication, networking, background processing, or major components.
- Do not rescan the repository when memory already contains the needed context. Inspect only relevant source files unless broader inspection is necessary.
- If memory conflicts with code or configuration, verify the implementation and correct the memory. Never preserve stale documentation.

## Required workflow for substantial tasks

1. Read this file and `PROJECT_MEMORY.md`.
2. Read `TODO.md` and/or `ARCHITECTURE.md` when the task touches their scope.
3. Inspect the relevant implementation.
4. Perform and validate the requested work.
5. Check whether functionality, status, decisions, configuration, operations, architecture, issues, limitations, or priorities changed.
6. Update the affected memory files in the same task before the final response.

A substantial task is incomplete while relevant memory is stale. Do not wait for the user to request memory maintenance. Tiny typo, formatting, or behavior-neutral refactoring changes do not require memory updates.

## What to update

- Update `PROJECT_MEMORY.md` for changes to functionality, project status, features, components, dependencies, configuration, runtime behavior, integrations, constraints, known issues, limitations, decisions, deployment assumptions, active work, or next steps.
- Update `ARCHITECTURE.md` for changes to boundaries, communication, APIs, data flow, storage, authentication/authorization, external systems, infrastructure, networking, runtime topology, deployment, workers, schedules, queues, caches, or CI/CD.
- Update `TODO.md` when work is completed, discovered, reprioritized, made obsolete, or when bugs or technical debt are introduced or resolved.

## Documentation discipline

- Keep memory concise, current, and project-specific. Modify existing sections instead of appending an endless history.
- Record verified facts. Mark uncertainty explicitly.
- Never store passwords, tokens, private keys, session data, authentication headers, certificate private material, or `.env` values.
- Prefer pointers to source and operational documentation over copied code.
- Preserve compatibility and production-data constraints. Remove obsolete statements promptly.
