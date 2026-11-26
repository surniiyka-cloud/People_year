# People Year · ТИАН-Трейд

Frontend: GitHub Pages. Backend: Supabase Edge Function `people-api` with an atomic, service-role-only PostgreSQL RPC. Data stays in the private `people` schema. The original Python server is retained for Railway rollback.

## Deployment

Production URL: https://surniiyka-cloud.github.io/People_year/
Admin: https://surniiyka-cloud.github.io/People_year/admin/
Supabase project: gsxroprhnimtrzjhvuah. No API key is needed in the frontend. The Edge Function uses only Supabase's built-in SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment secrets.

1. Apply `supabase/people_schema.sql` for a fresh database, then `supabase/migrations/20261126090000_api.sql`. Never reset an existing database.
2. Set the administrator bcrypt hash in `people.admin_credential` using a trusted management connection. Do not put passwords, hashes or migration data in Git.
3. Deploy `supabase/functions/people-api/index.ts` as `people-api`, with JWT gateway verification disabled: this function authenticates its own 256-bit bearer sessions. Both the SQL RPC and underlying tables reject anon/authenticated access.
4. Run `node --test tests/static.test.mjs`, `deno check supabase/functions/people-api/index.ts`, and `node scripts/build.mjs`. Publish only `dist/`.
5. Pages Source is GitHub Actions. `.github/workflows/pages.yml` tests and publishes only the static `dist/` directory on every push to main. The gh-pages branch retains the initial verified static snapshot.

## Private data migration and restoration

Use Node 24+: `node scripts/prepare-import.mjs --sqlite PATH_TO_BACKUP PRIVATE_SQL_OUTSIDE_REPO`. The command reads SQLite in read-only mode, checks integrity and foreign keys, then prepares one transaction that refuses a nonempty target. Apply that private SQL through a trusted database connection; never upload it to GitHub, Actions artifacts or Pages. For a JSON backup downloaded from the admin panel, use `--json` instead. Admin credentials and sessions are deliberately excluded from backups. A restore into a new project requires recreating the admin credential separately.

Compare every restored row, including IDs, code hashes, used flags and ballot candidates. A matching backup does not by itself prove the live Railway database has no newer writes. The supplied backup and a fresh live Railway backup were both fully reconciled before Railway was stopped.

## Behavior and privacy

All original admin tabs, employee editing/activation, code generation/reissue/revocation, seasons, test reset, turnout, Google Forms archive matching and XLSX import/export are preserved. XLSX exports neutralize formula prefixes. Uploads have compressed/decompressed size and worksheet limits. Backup format is now JSON, rather than SQLite.

Codes keep their original SHA-256 hashes. Random codes are shown only on issue. Sessions last one hour, are stored as hashes in PostgreSQL, and survive function restarts. The frontend keeps its bearer token in sessionStorage, isolated to its browser tab. Never include the token in a URL. Login rate limits persist in PostgreSQL (12 attempts per IP / 5 minutes, 180 globally).

Votes and participation flags are written atomically under a transaction lock. A ballot contains only a random ID, season and candidate, with no voter ID or timestamp. Self votes, repeated votes, inactive voters/candidates, revoked sessions and closed seasons are rejected server-side. Ranking is hidden until closing. Admin backups contain confidential raw data, so store them securely. Operators with privileged database access can observe transactions; this is not cryptographic anonymity. No application request bodies, passwords, codes or ballots are logged by the function.

## Tests

`node --test tests/static.test.mjs` checks deployment paths, asset retention and client/security boundaries. `python -m unittest test_server.py` checks the retained legacy server. `tests/test_edge.py` exercises the deployed API with a dedicated season 2099 and two synthetic employee IDs; supply PEOPLE_TEST_PASSWORD through a secure environment. Run it only during maintenance; it opens a test season briefly. Afterwards remove that season, the two synthetic employees and the archive labeled __migration_test_archive through the trusted management connection, then repeat the full backup comparison.

## Rollback

Railway has no active deployment and is disconnected from GitHub. The service and original persistent volume are retained for recovery. To recover the legacy server, connect a branch at commit 39bf3ef2d50b7c98393a404f1a5055fcc8390688 and deploy with the existing volume and variables. If switching back after accepting votes on Supabase, export and reconcile those votes first; two independent writable databases must not both be used for the same season.
