---
name: deploy-running-coach
description: Deploy, verify, troubleshoot, or roll back AI Running Coach on the family's Raspberry Pi using SSH and the existing Jenkins pipeline. Use for requests to release this app, check its live version, configure deployment secrets, or diagnose a failed Pi deployment.
---

# Deploy AI Running Coach

## Known installation

- Pi: `192.168.1.129`; confirmed SSH account: `g99trading`.
- SSH uses the operator's existing OpenSSH identity. Never read/copy private keys,
  disable host-key verification, or put passwords/API keys in commands or chat.
- Jenkins: `http://192.168.1.129:8080`, container `ci_cd_validation_jenkins_1`.
- Pipeline job: `ai-running-coach`; source: `Gianpy99/Running`, branch `main`.
- App container/image: `ai-running-coach` / `ai-running-coach:latest`.
- App LAN URL: `http://192.168.1.129:8095`; container port: `8090`.
- Public URL: `https://running.borrellofamily.co.uk`, behind family authentication.
- Persistent data: native PostgreSQL database `running_coach`, not the container layer.
- Jenkins credential IDs: `running-coach-database-url` and optional
  `running-coach-openai-api-key`.
- Full runbook: [deploy/README.md](../../../deploy/README.md).

These are discovery starting points, not permission to change unrelated Pi services.
Recheck live state before acting. Never reprovision an existing database, seed/reset
data, restart Jenkins, or change portal/DNS configuration for an ordinary app release.

## 1. Establish state

1. Read the runbook and `Jenkinsfile`. Inspect local Git status, current branch, recent
   commits and remote `main`. Preserve unrelated work.
2. Check whether Jenkins already deployed the intended commit. SCM polling runs about
   every three minutes; do not rebuild an already-current healthy app unnecessarily.
3. Use noninteractive SSH with a bounded connection timeout:

   ```powershell
   ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes g99trading@192.168.1.129 'id -un; uname -m'
   ```

4. On authentication failure, inspect identity-file names/agent configuration only.
   Do not guess passwords or switch accounts without the user's confirmation.
5. Check `/health`, the app's image ID/start time and Jenkins build metadata. Read only
   the necessary fields; never print `docker inspect` environment arrays, credential
   files, raw coaching contexts, or complete build logs.

## 2. Protect rollback and data

- Record the current successful Jenkins build number, Git revision and app image ID.
- Tag the current image `ai-running-coach:rollback-<build-number>` before replacing it.
  If that tag already exists, compare IDs; never overwrite a different rollback image.
- Before application/schema changes, take a server-side PostgreSQL custom-format
  backup using the existing administrator's noninteractive privileges. Keep it owned
  by `postgres`, mode `0600`, and report only its path/size, not its contents.
- Record workout/race counts without printing personal records. Account for legitimate
  concurrent user activity when comparing counts.
- Do not stop the healthy app during the image build or delete old images/backups.

## 3. Publish and deploy

- Run the smallest relevant existing validation for code changes. Documentation/skill
  changes need link/frontmatter/whitespace checks, not a new application test suite.
- Stage only the intended reviewed files. Check that example secrets are empty and
  real environment files are ignored; never stage secret files.
- Follow the user's commit/push preferences. When publishing is authorized as part of
  deployment, use a normal commit with the required co-author trailer; no force pushes.
- Deploy through the existing Jenkins job, not an ad hoc container with invented
  database credentials. Push the intended `main` revision and let SCM polling build,
  or trigger the existing job using an already-authorized Jenkins session.
- Keep `ENABLE_AI_COACHING` and `COACH_OPENAI_MODEL` at the operator's intended values.
  A missing optional key is not a reason to disable a previously configured key or
  fabricate one. Do not change the model/budget merely to make a check succeed.
- Wait with a bounded timeout (allow for ARM builds and SCM polling), recording build
  number/result/revision. If a build fails, inspect only relevant errors and sanitize
  any output before displaying it. Do not repeatedly trigger competing builds.

## 4. Verify the actual result

Require all applicable evidence before declaring success:

1. Jenkins `SUCCESS` for the intended Git revision, not just an older successful build.
2. Container running, LAN `/health` returning `{"status":"ok"}`, and persistent database
   access working.
3. A representative deployed source/static-file SHA-256 matching the local release, or
   equivalent immutable image revision evidence.
4. Expected coaching routes and static JavaScript available.
5. A **local-only** `POST /ai/coaching/preview` with
   `{"purpose":"next_training"}` works. Display only prompt version/model/key-configured
   boolean and coverage/count summaries, never the athlete's full context.
6. Existing workout/race data preserved; no re-seeding or reset.
7. Public route reachable with its existing authentication intact, where accessible.

Preview is free/local. Never invoke `/ai/coaching/generate` as a deployment smoke test:
it sends personal context to OpenAI and may incur charges.

If the key is absent, explicitly report that the app is deployed but API calls remain
disabled. Direct the user to Jenkins Secret text ID `running-coach-openai-api-key`,
then a build with `ENABLE_AI_COACHING=true`. Never request the key in chat or put it in
`.env.example`, Git, a build parameter, a Dockerfile, or image build arguments.

## 5. Failure and rollback

- Do not report success for a failed build or unhealthy container.
- Retain the previous image and protected database backup. Inspect the failure before
  changing anything else; do not reset the DB or force Git history back.
- Use the previous validated image/revision with the **same existing Jenkins credential
  binding** for a rollback. The standard job builds `main`; changing its source/image
  selection is a separate explicit operator action, not an existing rollback switch.
- If credential-safe rollback is not available, stop and state the exact blocker
  rather than reconstructing/printing secrets or guessing deployment arguments.
- Do not automatically restore a database backup: that can destroy newer workouts.
  A database restore requires explicit approval and a separate recovery plan.

## Windows-to-Linux command transport

Windows PowerShell here-string pipelines can append CRLF and break a Linux command's
last argument. For a multi-line **non-secret** remote script, remove CR characters and
send a base64-encoded script as an SSH command:

```powershell
$script = @'
set -eu
curl --fail --silent --show-error --max-time 8 http://127.0.0.1:8095/health
'@
$encoded = [Convert]::ToBase64String(
    [Text.Encoding]::UTF8.GetBytes(($script -replace "`r", '')))
ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes `
    g99trading@192.168.1.129 "printf '%s' '$encoded' | base64 -d | bash"
```

Base64 is not encryption. Never embed secret values in this script/command transport.
Use Jenkins credentials for secrets. Clean up only task-specific temporary files and
processes; retain deliberate rollback images and database backups.
