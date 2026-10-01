# Local single sign-on test server (Keycloak)

**Development and testing only.** A stand-in "district" identity provider
for trying single sign-on (Phase 5.4) on a laptop. `make_realm.py`
generates the realm with a fresh client secret and fresh passwords each
time, into `out/` (gitignored), so no credential is committed.

1. Generate the realm (pass the api's address as the browser reaches it):

   ```bash
   python dev/keycloak/make_realm.py http://localhost:8000
   ```

2. Start Keycloak (Docker, port 8180 on this computer only):

   ```bash
   docker run --rm --name isd-keycloak -p 127.0.0.1:8180:8080 -v "$PWD/dev/keycloak/out:/opt/keycloak/data/import:ro" quay.io/keycloak/keycloak:26.3 start-dev --import-realm
   ```

3. Start the api with the settings in `out/api-sso.env`; the sign-in
   page then shows "Sign in with your district account".

`out/users.txt` lists who can sign in: `dispatcher@demo.example.org` and
`driver.jordan@demo.example.org` match the demo district's accounts;
`not.in.app@demo.example.org` has no account in the app, to see that
message. Keycloak's ID tokens don't report a second factor, so staff are
then asked for the app's own two-step code, as with any provider that
doesn't say.
