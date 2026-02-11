# Nests API Error Shapes

Canonical error response shapes to keep API behavior consistent.

## Common Shape

```json
{
  "error": "string_code",
  "message": "Human-readable explanation"
}
```

## Specific Errors

### nest_limit_reached (free cap)
```json
{
  "error": "nest_limit_reached",
  "message": "Free nests are currently at capacity. Upgrade to create a new nest.",
  "upgrade_url": "/billing/upgrade"
}
```

### rate_limited
```json
{
  "error": "rate_limited",
  "message": "Too many requests. Please try again later."
}
```

### feature_not_allowed
```json
{
  "error": "feature_not_allowed",
  "message": "This feature is not included in your plan."
}
```

### forbidden
```json
{
  "error": "forbidden",
  "message": "You do not have permission to perform this action."
}
```

### invite_required
```json
{
  "error": "invite_required",
  "message": "This nest is invite-only. Provide a valid invite token."
}
```

### not_found
```json
{
  "error": "not_found",
  "message": "Nest not found."
}
```
