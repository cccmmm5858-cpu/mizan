# Critical foundations — review notes

Branch: `fix/critical-foundations`. No merge, deployment, or changes to `main`.

## Changes

- The frontend sends `financial`. The backend accepts only that canonical case type; legacy `f`, personal cases, and unknown types are rejected rather than selecting a personal prompt.
- Retrieval searches normalized article **content** with explicit query expansions. IDs are source + a hash of the article title, independent of array order and content edits. Old manually indexed mappings are removed. Article browsing uses the backend database instead of a second embedded copy.
- `/api/chat` requires `Authorization: Bearer <CHAT_ACCESS_TOKEN>`. Missing/short configuration fails closed. The token must have at least 32 characters, be generated randomly by the operator, and be distributed privately. The browser reads it from a password input, keeps it in memory, and does not persist it. This is a temporary shared access credential, not a user-account system.
- An atomic SQLite limit allows 10 requests per 60-second fixed window for the shared credential across Gunicorn workers on one host. Rejected/malformed authenticated requests also consume the budget. Forwarded IP headers cannot change it. All workers must use the same `RATE_LIMIT_DB`. Multiple hosts require a shared limiter before any future deployment.
- Payload size is capped at 128 KiB. Only alternating user/assistant text messages are accepted, with per-message and total limits. Retrieval derives its query from user messages, not a separate client-controlled query field. Provider calls have a 30-second timeout and no automatic retries.
- Client errors are generic. Logs contain exception classes only, not provider exception text, credentials, or conversation bodies. API responses are not cached.
- Reset increments a conversation generation and aborts the previous fetch. All chat success/error/finalization callbacks ignore superseded generations. Reset restores the send control; the retrieval panel is cleared when sending and when rendering a new response.
- PDF/image controls and fake analysis prompts are removed. Attachments and image/document content blocks are rejected server-side. Personal cases are disabled in both layers.
- The model can select retrieved IDs and fixed follow-up questions only. Its output must match a strict JSON schema; unknown IDs, invented questions, or additional prose are rejected. The server renders titles and content verbatim from the retrieved records. Empty retrieval supplies no fallback citation and skips the provider. **Free-form analysis, drafting, and strength scoring are temporarily unavailable.** The misleading fixed evidence mapping and scores were also removed.
- `.gitignore` excludes local credentials, environments, logs, caches, and rate-limit files. `.env.example` contains names with empty values only.

## Configuration (not performed here)

Set `ANTHROPIC_API_KEY`, `CHAT_ACCESS_TOKEN`, and optionally `RATE_LIMIT_DB` in the server environment. `.env.example` is documentation and is not auto-loaded. Use HTTPS for the access token. The existing Procfile is unchanged. No real credentials were configured and no real provider calls were made.

## Verification in this environment

- `python -m unittest discover -s tests -v`: **13 passed, 9 skipped**. Successful tests cover all four requested queries (كفالة، واتساب، إقرار، مطالبة مالية), expected legal-topic text, stable IDs/ranking under reorder, Arabic normalization, authentication, case validation, attachments, exact citation rendering, hallucination rejection, and limiter sharing/concurrency/reset. The WhatsApp regression test requires evidence articles 53, 55, and 57 in the default top-eight results, including with Arabic diacritics and reversed database order.
- `node tests/test_frontend.cjs`: **5 scenarios passed**. Executes the actual frontend script with a small DOM/fetch fixture, checks the financial payload and authorization header, disabled personal/upload controls, no token persistence, and HTML escaping for article text. Deferred-response tests cover reset followed by late success, late failure, and delayed JSON parsing; an old request cannot alter new messages or unlock the new request. Another test checks that empty retrieval clears and hides old article tags.
- Python syntax parsing with `ast.parse` for the application and Python tests: **passed**.
- `git diff --check`: **passed**.
- API tests are saved in `tests/test_api.py` and mock `anthropic.Anthropic`; they never call Anthropic. They could not run because Flask and Anthropic are absent. No dependency installation was retried after the user's instruction. Live Flask routes, framework error handling, SDK compatibility, and browser rendering therefore remain unverified here.
- Pattern scanning found no API keys/private keys in the working files or 16 unique historical file versions accessible through GitHub. Two of the 16 listed historical commits had unavailable trees (404), so the history scan is partial. This is a pattern scan, not proof that every possible credential format is absent.

The legal database was used as supplied, without editing legal text or certifying its completeness, official provenance, or dates. Those remain a separate source audit.
