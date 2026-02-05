# Ship Command

Commit changes, update changelog, and deploy to production.

## Workflow

1. **Check git status** - Review staged and unstaged changes
2. **Stage relevant files** - Add modified files (exclude .cache, .env, local_config.yaml)
3. **Create commit** - With descriptive message following repo conventions
4. **Update changelog** - Add entry to `docs/CHANGELOG.md` under today's date
5. **Push to origin** - Push commit to main branch
6. **Deploy to production** - Sync code and rebuild containers

## Deployment Details

- **Server**: deploy@192.241.153.83
- **Path**: /opt/andre
- **Method**: rsync + docker compose rebuild

### Rsync Command
```bash
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.env' --exclude='local_config.yaml' --exclude='.cache' \
  --exclude='node_modules' \
  /Users/dylanbochman/repos/Andre/ deploy@192.241.153.83:/opt/andre/
```

### Rebuild Command
```bash
ssh deploy@192.241.153.83 "cd /opt/andre && docker compose up -d --build"
```

### Verify Deployment
```bash
curl -s -o /dev/null -w "%{http_code}" https://andre.dylanbochman.com/health
```

## Commit Message Style

Follow the existing repo convention:
- Imperative mood ("Fix bug" not "Fixed bug")
- First line is summary (under 72 chars)
- Blank line then details if needed
- End with `Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>`

## Changelog Format

Add entries under `## YYYY-MM-DD` section in `docs/CHANGELOG.md`:

```markdown
### Bug Fixes
- **Short Title** - Description of what was fixed
  - Implementation detail
  - Commit: `abc1234`

### Features
- **Feature Name** - Description
  - Details
```

## Usage

When user says "ship it", "commit and deploy", or similar:
1. Execute this full workflow
2. Report the commit hash and deployment status
3. Confirm health check passes
