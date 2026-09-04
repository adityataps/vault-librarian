# Vault Librarian Config

Edit the values below and save — the service hot-reloads this file.

```yaml
debounce_seconds: 5
workflows:
  format: {enabled: true, model: fast}
  backlink: {enabled: true, model: fast}
  frontmatter: {enabled: true, model: fast}
  spellcheck: {enabled: true, model: fast}
  mermaid: {enabled: true, model: fast}
  research_directive: {enabled: true, model: strong}
  org_agent: {enabled: false, model: strong, schedule: "0 6 * * *"}
models:
  fast: {provider: github_copilot, model: gpt-4.1-mini, timeout_seconds: 30, max_retries: 3}
  strong: {provider: anthropic, model: claude-sonnet, timeout_seconds: 60, max_retries: 3}
ignore_paths:
  - Attachments/
  - .obsidian/
  - Templates/
backup:
  enabled: false
  remote: null
  schedule: "0 3 * * *"
mcp:
  enabled: false
  bind: 127.0.0.1
  token: null
```
