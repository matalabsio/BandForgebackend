# Speaking release notifications

## Deployment record — 21 July 2026

- Production Supabase: Speaking migrations `speaking_responses` through
  `speaking_phase13_indexes` applied and verified.
- Local disposable staging: clean reset, idempotent migration replay,
  `supabase db lint`, approval replay, outbox enqueue, leasing, and reopen
  cancellation passed.
- Automated acceptance: 76 focused backend tests plus frontend typecheck,
  lint, report, Phase 13, and Speaking lifecycle suites passed.
- Still required before live delivery: revoke/rotate the exposed Resend key,
  use a verified `EMAIL_FROM`, authenticate Railway, deploy the API and
  always-on worker, then run one controlled real-account release.
- WhatsApp is disabled for the current launch (`META_WHATSAPP_ENABLED=false`);
  its dormant provider/webhook code is not a deployment requirement.

Apply `20260721127000_speaking_release_notifications.sql` through the normal
Supabase migration workflow before deploying the API or worker. Do not run the
worker against an older schema.

Railway uses separate services built from the same backend image:

- API: keep the existing `railway.toml` deployment and API start command.
- Worker: `bash scripts/run_notification_worker.sh` (always on, no public domain).
- Recovery sweeper (optional): `bash scripts/sweep_notification_outbox.sh` as a
  cron every five minutes. Claims are atomic, so overlap with the worker is safe.

Both worker and API need the Supabase service-role key and frontend URL. Email
delivery additionally needs `RESEND_API_KEY` and `EMAIL_FROM`.

If WhatsApp is enabled in a future release, configure the Meta callback as:

`https://<api-host>/api/webhooks/meta/whatsapp`

Use the configured verify token for GET verification and the app secret for
signed POST callbacks. The approved utility template must accept exactly two
body text parameters: the safe student display name and authenticated report
URL. It must not include a score or transcript.
