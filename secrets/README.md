This directory holds Docker secret files for `docker-compose.prod.yml`.
Everything except this README is gitignored — never commit a real
secret file.

Create the one file this compose setup needs:

```bash
openssl rand -base64 32 | tr -d '\n' > secrets/postgres_password.txt
chmod 600 secrets/postgres_password.txt
```

`tr -d '\n'` matters: Postgres reads the file's exact contents as the
password, so a trailing newline would become part of it. Use the same
password when you set `ISD_API_DATABASE_URL` in `.env` — see
`.env.prod.example` and `docs/deployment.md`.
