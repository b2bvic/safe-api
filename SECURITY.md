# Security policy

## Report a vulnerability

Use the repository’s private GitHub vulnerability reporting option when available.
If it is unavailable, email victor@scalewithsearch.com with a minimal reproduction.
Do not include credentials, private transcripts, or customer data in a public issue.

## Support scope

Reports against the current default branch receive review. There is no guaranteed response time or long-term release support.

## Data and permission boundaries

Payloads and server errors can enter audit logs. Redact sensitive fields before calling the client.
Execution mode is a setting, not proof of human approval. Enforce authorization in your calling service.

Keep tokens in environment variables or your secret store. Use temporary directories and synthetic data for tests.
