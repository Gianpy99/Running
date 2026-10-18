# Deploying AI Running Coach to the Family Portal (Raspberry Pi)

This app follows the same pattern as **MyGarage** / **AudibleConverter**: its own
`Dockerfile` + `Jenkinsfile`, deployed as a Docker container by the Jenkins instance
running on the Pi. Jenkins polls GitHub every ~3 min and rebuilds on new commits.

| Item | Value |
|---|---|
| Repo | `github.com/Gianpy99/Running.git` (branch `main`) |
| Container port (internal) | `8090` |
| Host port (Pi) | `8095` |
| Public URL | `http://running.borrellofamily.co.uk` (family basic-auth) |
| Database | native PostgreSQL 15 on the Pi, `192.168.1.129:5432`, DB `running_coach` |
| Jenkins job | `ai-running-coach` |
| DB secret (Jenkins) | `running-coach-database-url` (Secret text) |
| Health endpoint | `GET /health` (checks DB connectivity) |

> Infrastructure facts: Pi `192.168.1.129`, SSH user `g99trading`, Jenkins container
> `ci_cd_validation_jenkins_1`. Adjust if these change.

---

## 1. Create the database on the Pi's PostgreSQL

The Pi runs **native PostgreSQL 15** on `:5432` (`listen_addresses='*'`), one DB per app
(alongside `mygarage`, `trading`). Use the idempotent provisioning script — it generates a
strong password server-side (never printed), creates the role + database, adds the
`pg_hba.conf` rules for the Docker bridge, and writes the `DATABASE_URL` straight into the
Jenkins credential file:

```powershell
# From this repo (Windows), pipe the script to the Pi over SSH:
((Get-Content deploy/provision-db.sh -Raw) -replace "`r`n","`n") |
  ssh g99trading@192.168.1.129 'bash -s'
```

The app creates its tables automatically on first connect. The container also
seeds the bundled regression fixtures on first run (`COACH_AUTO_SEED=1`).

## 2. Push the code to GitHub

```powershell
cd C:\Development\Running
git add -A
git commit -m "Add Postgres backend + Docker/Jenkins deployment"
git push origin main
```

## 3. Create the Jenkins job + DB secret (on the Pi)

> If you ran `deploy/provision-db.sh` in step 1 it already wrote the DB secret file
> (`/var/jenkins_home/running-coach-dburl`). In that case skip step (a) below.

Copy this repo's `deploy/` helpers onto the Pi, then:

```bash
# a) (only if not done by provision-db.sh) inject the DATABASE_URL secret file
printf '%s' 'postgresql://running_coach:<PASSWORD>@192.168.1.129:5432/running_coach' \
  | docker exec -i ci_cd_validation_jenkins_1 tee /var/jenkins_home/running-coach-dburl >/dev/null
docker cp deploy/running-coach-db-url.groovy ci_cd_validation_jenkins_1:/var/jenkins_home/init.groovy.d/running-coach-db-url.groovy

# b) create the pipeline job (points at the GitHub repo + Jenkinsfile)
docker cp deploy/running-coach-setup.groovy ci_cd_validation_jenkins_1:/var/jenkins_home/init.groovy.d/running-coach-setup.groovy

# c) apply
docker restart ci_cd_validation_jenkins_1
```

Both groovy scripts are idempotent and self-delete after running. The first build
starts automatically; thereafter `pollSCM` picks up new commits.

Verify on the Pi: `docker logs -f ai-running-coach` and `curl http://192.168.1.129:8095/health`.

## 4. Register the app in the portal dashboard + reverse proxy

From the FamilyPortal repo (adds the tile in `services.json` and the LAN path route):

```powershell
C:\Development\FamilyPortal\register-app.ps1 `
    -Id "running" -Name "AI Running Coach" `
    -Description "Deterministic running analytics & readiness" `
    -Category "Health & Fitness" -Icon "🏃" -Color "#22c55e" -Port 8095
```

Then add the **subdomain + basic-auth** route: paste the block from
[deploy/caddy-subdomain.txt](caddy-subdomain.txt) into
`FamilyPortal/reverse-proxy/Caddyfile` (next to the other `*.borrellofamily.co.uk`
blocks) and publish + reload Caddy:

```powershell
C:\Development\FamilyPortal\deploy.ps1 -SetupCaddy
```

## 5. Public DNS (Cloudflare Tunnel)

Route the subdomain through the existing tunnel (run on the Pi):

```bash
cloudflared tunnel route dns family-portal running.borrellofamily.co.uk
```

(or add `running.borrellofamily.co.uk` to `SUBDOMAINS` in
`FamilyPortal/scripts/pi/cloudflare-tunnel-setup.sh` and re-run it).

## 6. Verify

- LAN: `http://192.168.1.129:8095/` (dashboard) and `/health` → `{"status":"ok"}`
- Public: `http://running.borrellofamily.co.uk` (behind family login)
- Data: `GET /workouts` should list the seeded regression runs.

---

## Notes

- **ARM wheels**: `psycopg[binary]` ships aarch64 wheels — fine on a 64-bit Pi OS.
  On 32-bit (armv7) it would need a source build (`psycopg[c]` + `libpq-dev gcc`).
- **Re-seeding**: seeding only runs when the `workouts` table is empty. To force a
  re-import: `docker exec ai-running-coach python -m app.cli import --raw data/regression --db "$DATABASE_URL" --report data/processed/data_quality.json`.
- **Local test of the image**: `docker compose up --build` (uses `.env`; copy from `.env.example`).

## Optional OpenAI coaching

The deployment remains usable without an API key: previews, ChatGPT copy/export, local
analytics and deterministic plans all work. Viewing/importing a workout never calls
OpenAI. API charges occur only after an explicit preview and **Ask via API**.

### Where to paste the key on the Pi

Use the **Jenkins web UI**, not a repository file or a pipeline parameter:

1. Open **Manage Jenkins -> Credentials -> System -> Global credentials -> Add Credentials**.
2. Select **Secret text**.
3. Paste the OpenAI API key into **Secret**.
4. Set **ID** to `running-coach-openai-api-key` and save.
5. Run the `ai-running-coach` job using **Build with Parameters**, enable
   `ENABLE_AI_COACHING`, and leave `COACH_OPENAI_MODEL=gpt-5-mini` initially.
   The parameters appear after Jenkins first loads the updated pipeline.
6. The pipeline preserves your last parameter selections as defaults for subsequent
   builds, including SCM polling. Verify the coaching preview reports that the API is
   configured. Do not print the container environment to check a key.

The pipeline binds the secret to the container at runtime; it is not a Docker build
argument, image layer, Git file, or browser setting. The optional credential is not
required when `ENABLE_AI_COACHING` is false. Rotate/revoke keys in OpenAI and replace the
Jenkins credential before redeploying. Docker/Jenkins administrators can access runtime
secrets, so protect their accounts and backups.

For local development only, paste a key into the git-ignored `.env` as
`OPENAI_API_KEY=...`; use the native `--env-file .env` command in the main README or
Docker Compose. The Pi and Windows have separate runtime environments; neither copies
the other's `.env`. Prefer separate OpenAI project keys/budgets for development and Pi.

### Operation and privacy

- Set an OpenAI project budget/alerts and access limits before enabling API coaching.
  The selected model must support Responses API Structured Outputs.
- The selected prompt/context is sent to OpenAI; no raw trackpoints, GPS coordinates,
  raw files, body measurements or API keys are included. Athlete-entered notes/profile
  may contain personal information: inspect the preview and remove unwanted details.
- `store=false` disables Responses application-state storage; it is **not** a promise
  of zero provider retention. Review OpenAI's current data controls for your account.
- Contexts and advice are stored in the application's database and its backups. The
  existing family-portal authentication must protect all routes, including `/ai/*`.
  Do not expose the container port directly to the Internet. The app has no separate
  per-user authorization or distributed cost limiter.
- One process allows one paid request at a time, with no automatic retries and a
  90-second provider timeout. Identical context/model/prompt requests reuse a result.
  Multi-worker deployments would need a shared request/budget lock.
- Errors are shown explicitly; failed/refused/incomplete/unsafe advice is not saved or
  silently replaced by a successful-looking AI result. A timeout may still incur
  provider charges; inspect the provider dashboard before retrying.
