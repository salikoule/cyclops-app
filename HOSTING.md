# Host Cyclops

The public address is `https://cyclops.craftify.works`. Do the steps in order. DNS has to point at the server before the deploy, or the certificate request fails.

The deploy command is `scripts/deploy.sh user@host` from `cyclops_self_host`. It installs Docker if the host does not have it, copies the app to `/opt/cyclops`, and starts it. SSH must already accept a key. The script does not ask for a password.

## 1. SSH key

On the Mac:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519
```

Press enter if a key is already there. Copy the public key:

```bash
pbcopy < ~/.ssh/id_ed25519.pub
```

## 2. Hetzner server

1. Open [Hetzner Cloud](https://console.hetzner.cloud/) and create a project.
2. Under Security, add an SSH key. Paste the public key from step 1.
3. Create a server:
   - Location: Falkenstein or Nuremberg
   - Image: Ubuntu 24.04
   - Type: CX23 (2 vCPU, 4 GB)
   - Public IPv4: on
   - SSH key: the one you just added
4. Copy the IPv4 address. Below it is called `THE_IP`.

From the Mac, accept the host key once:

```bash
ssh root@THE_IP
```

Type `exit` after the login works.

## 3. DNS

`craftify.works` stays where it is. Add only the Cyclops name.

1. Namecheap, Domain List, `craftify.works`, Advanced DNS.
2. Add a record: type `A`, host `cyclops`, value `THE_IP`.
3. Leave the `@` record alone.

Check from the Mac. Wait until this prints `THE_IP`:

```bash
dig +short cyclops.craftify.works
```

## 4. Google sign-in

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project named Cyclops.
2. APIs & Services, OAuth consent screen. User type External. App name Cyclops. Support email `sali@craftify.works`.
3. While the app is in Testing, add every Google account that should be allowed to sign in as a test user.
4. Credentials, Create credentials, OAuth client ID, Web application.
5. Authorized JavaScript origin: `https://cyclops.craftify.works`
6. Authorized redirect URI: `https://cyclops.craftify.works/_/client_auth_callback`
7. Copy the client ID and the client secret.

## 5. Microsoft sign-in

1. Open [App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) and choose New registration.
2. Name: Cyclops.
3. Supported accounts: any organizational directory and personal Microsoft accounts.
4. Redirect URI: platform Web, value `https://cyclops.craftify.works/_/microsoft_auth_callback`.
5. Register. On Overview, copy Application (client) ID.
6. Certificates & secrets, New client secret. Copy the Value immediately. Azure hides it after you leave the page.

Leave the tenant as `common`. That matches the account type chosen above.

## 6. Mail

Signup and password reset send through `sali@craftify.works`.

1. Sign in to that Google account.
2. Turn on 2-step verification if it is off.
3. Open [App passwords](https://myaccount.google.com/apppasswords) and create one named Cyclops.
4. Copy the 16 letters. Remove the spaces.

If that page is missing, the Workspace admin has to allow app passwords for the account before this step can finish.

## 7. The env file

From `cyclops_self_host`:

```bash
cp .env.production.example .env.production
```

Fill the empty values:

| Name | Value |
| --- | --- |
| `POSTGRES_PASSWORD` | a long string of letters and digits |
| `SMTP_PASSWORD` | the Google app password |
| `GOOGLE_CLIENT_ID` | from step 4 |
| `GOOGLE_CLIENT_SECRET` | from step 4 |
| `MICROSOFT_APP_ID` | Application (client) ID |
| `MICROSOFT_APP_SECRET` | the secret Value |

Leave the other lines as they are in the example. A symbol in `POSTGRES_PASSWORD` breaks the database URL. The file stays off git.

## 8. Deploy

```bash
scripts/deploy.sh root@THE_IP
```

When it finishes, open `https://cyclops.craftify.works`. The certificate is requested on that first visit, so give it a minute if the browser complains once.

The plant tables are empty at this point.

## 9. Copy the plant rows

Do this while the local Docker app is running, and before anyone creates an account on the new site. The local database is on port 5433, user `cyclops`, password `cyclops`.

```bash
PGPASSWORD=cyclops pg_dump \
  -h 127.0.0.1 -p 5433 -U cyclops -d cyclops \
  --schema=plant --data-only --no-owner --no-privileges \
  -f /tmp/cyclops-plant-data.sql

scp /tmp/cyclops-plant-data.sql root@THE_IP:/tmp/cyclops-plant-data.sql

ssh root@THE_IP 'sudo docker exec -i cyclops-prod-db-1 psql -U cyclops -d cyclops -v ON_ERROR_STOP=1' \
  < /tmp/cyclops-plant-data.sql
```

Then move the id counters past the copied rows:

```bash
ssh root@THE_IP "sudo docker exec -i cyclops-prod-db-1 psql -U cyclops -d cyclops -v ON_ERROR_STOP=1" <<'SQL'
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.relname AS table_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'plant' AND c.relkind = 'r'
      AND pg_get_serial_sequence('plant.' || c.relname, 'id') IS NOT NULL
  LOOP
    EXECUTE format(
      'SELECT setval(%L, GREATEST((SELECT COALESCE(MAX(id), 1) FROM plant.%I), 1))',
      pg_get_serial_sequence('plant.' || r.table_name, 'id'),
      r.table_name
    );
  END LOOP;
END $$;
SQL
```

Delete `/tmp/cyclops-plant-data.sql` on the Mac and on the server when the restore has finished. Sign-in accounts are not in that dump.

## 10. First account

On `https://cyclops.craftify.works`, create an account. The first account becomes the administrator.

A confirmation message should arrive at that address. If it does, mail is working. Google and Microsoft use the buttons under the password field.
