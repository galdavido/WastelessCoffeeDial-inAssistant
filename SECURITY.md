# Security Policy

## Reporting a Vulnerability

Please **do not** publicly disclose security vulnerabilities. Instead, email `security@example.com` (or contact the maintainer privately via GitHub) with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge your report within 48 hours and work toward a fix.

## Security Best Practices

### For Users

1. **Store secrets securely**: Keep `.env` locally and never commit it. Rotate API keys if they are ever exposed.
2. **Validate input**: Only upload coffee bag photos from trusted sources.
3. **Bot permissions**: Ensure the Discord bot has minimal required permissions (Send Messages, Read Message History, Add Reactions).
4. **Database access**: Restrict PostgreSQL access to localhost or secure networks.

### For Contributors

1. **No secrets in code**: Do not hardcode API keys, tokens, or credentials.
2. **Use dotenv**: Store sensitive configuration in `.env` (ignored by `.gitignore`).
3. **Validate external input**: Sanitize web scraper output before storing in the database.
4. **Review dependencies**: Keep `requirements.txt` pinned and regularly update for security patches.

## Known Limitations

- **External API dependencies**: Vision analysis and embedding generation rely on Google Gemini API. Ensure your API key has appropriate quota and access controls.
- **Database**: PostgreSQL should be run on isolated networks in production.
- **Discord**: Bot token should be rotated immediately if exposed.

## Updates

We aim to review security best practices quarterly and welcome community suggestions.
