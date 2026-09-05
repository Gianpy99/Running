#!/usr/bin/env bash
# Provision the running_coach database on the Pi's native PostgreSQL 15 and write
# the DATABASE_URL into the Jenkins credential file. Idempotent.
#
# Run on the Pi, or pipe from Windows:
#   ((Get-Content deploy/provision-db.sh -Raw) -replace "`r`n","`n") | ssh g99trading@192.168.1.129 'bash -s'
#
# The DB password is generated here and never printed. Re-running rotates it and
# re-writes the Jenkins secret file.
set -euo pipefail

DB=running_coach
DBUSER=running_coach
JENKINS=ci_cd_validation_jenkins_1
HBA=/etc/postgresql/15/main/pg_hba.conf

# URL-safe password (hex) so it needs no percent-encoding in the DSN.
DBPASS=$(openssl rand -hex 24)

echo "[provision] creating/updating role '$DBUSER' ..."
sudo -u postgres psql -v ON_ERROR_STOP=1 -qc \
  "DO \$\$ BEGIN
     IF EXISTS (SELECT FROM pg_roles WHERE rolname='${DBUSER}') THEN
       ALTER ROLE ${DBUSER} LOGIN PASSWORD '${DBPASS}';
     ELSE
       CREATE ROLE ${DBUSER} LOGIN PASSWORD '${DBPASS}';
     END IF;
   END \$\$;"

echo "[provision] creating database '$DB' if missing ..."
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB}'" | grep -q 1; then
  sudo -u postgres createdb -O "${DBUSER}" "${DB}"
fi
sudo -u postgres psql -v ON_ERROR_STOP=1 -qc "GRANT ALL PRIVILEGES ON DATABASE ${DB} TO ${DBUSER};"
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB}" -qc \
  "GRANT ALL ON SCHEMA public TO ${DBUSER}; ALTER SCHEMA public OWNER TO ${DBUSER};"

echo "[provision] ensuring pg_hba.conf rules ..."
if ! sudo grep -q "${DB}" "$HBA"; then
  sudo cp "$HBA" "${HBA}.bak.$(date +%s)"
  sudo tee -a "$HBA" >/dev/null <<HBAEOF

# AI Running Coach (container -> host PostgreSQL)
host    ${DB}    ${DBUSER}    192.168.1.0/24    scram-sha-256
host    ${DB}    ${DBUSER}    172.16.0.0/12     scram-sha-256
HBAEOF
  sudo systemctl reload postgresql
  echo "[provision] pg_hba rules added and postgres reloaded."
else
  echo "[provision] pg_hba rules already present."
fi

echo "[provision] writing DATABASE_URL into Jenkins credential file ..."
DBURL="postgresql://${DBUSER}:${DBPASS}@192.168.1.129:5432/${DB}"
printf '%s' "$DBURL" | docker exec -i "$JENKINS" tee /var/jenkins_home/running-coach-dburl >/dev/null

echo "[provision] done. DB=${DB} USER=${DBUSER} (password not shown)."
