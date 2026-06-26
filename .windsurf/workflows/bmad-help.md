- --

name: 'help'
description: 'Get unstuck by showing what workflow steps come next or answering questions about what to do'

- --

# help

Use the installed BMad Help catalog and project artifacts:

1. Read `{project-root}/_bmad/_config/bmad-help.csv`.
2. Read relevant module config from `{project-root}/_bmad/**/config.yaml`.
3. Inspect `{project-root}/_bmad-output/**` for existing planning, implementation, and test artifacts.
4. Recommend the next BMad skill or workflow from the catalog, using the user's current request and existing artifacts as context.

Do not read `{project-root}/_bmad/core/tasks/help.md`; this project uses the installed BMad catalog-based help layout.
