This directory holds Docker secret files for `docker-compose.prod.yml`.
Everything except this README is gitignored — never commit a real
secret file.

Create the two files this compose setup needs:

```bash
openssl rand -hex 32 | tr -d '\n' > secrets/postgres_password.txt
openssl rand -hex 32 | tr -d '\n' > secrets/restic_password.txt
chmod 600 secrets/postgres_password.txt secrets/restic_password.txt
```

`tr -d '\n'` matters: Postgres reads the file's exact contents as the
password, so a trailing newline would become part of it. Hex rather than
base64, because the database password also goes inside
`ISD_API_DATABASE_URL` in `.env`, where `/` and `+` would need escaping —
see `.env.prod.example` and `docs/deployment.md`. Keep a copy of the
backup password (`restic_password.txt`) off the server: without it no
backup can be read.
