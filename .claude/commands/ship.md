# Ship Command

Commit changes, update changelog, and deploy to production.

## Workflow

1. **Check git status** - Review staged and unstaged changes
2. **Stage relevant files** - Add modified files (exclude .cache, .env, local_config.yaml)
3. **Create commit** - With descriptive message following repo conventions
4. **Update changelog** - Add entry to `docs/changelog.md` under today's date
5. **Push to origin** - Push commit to main branch
6. **Deploy to production** - Sync code and rebuild containers

## Deployment Details

- **Server**: deploy@andre.dylanbochman.com
- **Path**: /opt/echonest
- **Method**: rsync + docker compose rebuild

### Rsync Command
```bash
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.env' --exclude='local_config.yaml' --exclude='.cache' \
  --exclude='node_modules' \
  /Users/dylanbochman/repos/EchoNest/ deploy@andre.dylanbochman.com:/opt/echonest/
```

### Rebuild Command
```bash
ssh deploy@andre.dylanbochman.com "cd /opt/echonest && docker compose up -d --build"
```

### Verify Deployment
```bash
curl -s -o /dev/null -w "%{http_code}" https://echone.st/health
```

## Commit Message Style

Follow the existing repo convention:
- Imperative mood ("Fix bug" not "Fixed bug")
- First line is summary (under 72 chars)
- Blank line then details if needed
- End with `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`

## Changelog Format

Add entries under `## YYYY-MM-DD` section in `docs/changelog.md`:

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
