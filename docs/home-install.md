# Installing on a Windows PC

One script installs and runs the whole system on a Windows 10 or 11 PC,
loaded with a fictional school district, for you and anyone on the same
Wi-Fi to try. It's the production stack itself (PostgreSQL, the API, the
solver, the web app and an HTTPS proxy), not a cut-down version.

## What you need

- A Windows 10 or 11 PC with at least 8 GB of memory and 15 GB of free disk.
- Permission from the repository's owner to download the code (the
  repository is private: ask to be added as a collaborator on GitHub).
- An internet connection for the first install, which downloads Docker
  Desktop and the system's building blocks. After that it runs offline.

## Install

1. Get the code. Either:
   - with Git (needed later for `update`):

     ```powershell
     winget install -e --id Git.Git
     git clone https://github.com/giddy-mpungu/isd-bus-routing.git
     ```

     (Close and reopen the terminal after installing Git.)
   - or download the ZIP from the repository's GitHub page (**Code** →
     **Download ZIP**) and unzip it.
2. Open the `isd-bus-routing` folder and double-click **`deploy.cmd`**.
3. If Docker Desktop isn't installed, the script offers to install it.
   Say yes, then restart the PC if Windows asks, open Docker Desktop once
   to accept its terms, and double-click `deploy.cmd` again.
4. The first run builds everything, which takes several minutes. At the
   end it asks whether other devices on your home network may reach it
   (Windows then asks for permission to open the firewall for the local
   network only), and prints:
   - the address on this PC, **https://localhost**;
   - the address for phones and other computers on the same Wi-Fi, such
     as **https://192.168.1.23**;
   - one login per role (administrator, dispatcher, drivers, a school, a
     parent, a student), with their passwords.

Run `deploy.cmd credentials` from a terminal in the folder to see the
logins again; they're also in `secrets\home-credentials.json`.

## The certificate warning

The site uses HTTPS with a certificate made by this PC, not one from the
internet, so browsers warn the first time. Choose **Advanced** and then
**Continue** (or **Proceed**). To stop the warning on this PC, run
`deploy.cmd trust` and say yes when Windows asks. For a phone or another
computer, copy `secrets\home-ca.crt` to it and install it as a trusted
certificate there, or keep clicking through the warning.

## Signing in

The administrator and dispatcher need an authenticator app (such as
Google Authenticator or Microsoft Authenticator) for two-step sign-in:
the first sign-in shows a QR code to scan. Drivers, the school, parents
and students sign in with their password alone.

Emails the system sends (password resets, set-up emails for new
accounts, bus-time changes) don't go anywhere real: they land in a test
inbox at **http://localhost:8025**, on this PC only.

## Everyday commands

From a terminal in the folder:

| Command | What it does |
|---|---|
| `deploy.cmd` | Start it (after a restart, or after `stop`) |
| `deploy.cmd update` | Get the latest version and restart; data is kept and backed up first |
| `deploy.cmd stop` | Stop it; data is kept |
| `deploy.cmd status` | Show what's running |
| `deploy.cmd logs` | Follow the logs (Ctrl+C to stop) |
| `deploy.cmd credentials` | Print the logins again |
| `deploy.cmd trust` | Trust the HTTPS certificate on this PC |
| `deploy.cmd backup` | Back up now (it also does so every night, into `home-backups`) |
| `deploy.cmd reset` | Delete everything this install holds and start over |

Docker Desktop starts the system again by itself when the PC restarts, as
long as Docker Desktop is set to start when you sign in (its default).

## Good to know

- Everything stays on this PC. Nothing is reachable from the internet;
  other devices can only reach it on the same home network, and only if
  you said yes to the firewall question.
- Windows only lets other devices in when it treats the Wi-Fi as a
  **Private** network. The script warns if it's set to Public; change it
  under Settings → Network & internet → Wi-Fi → your network.
- The home address can change when the router restarts; running
  `deploy.cmd` again picks up the new one.
- It uses ports 80 and 443 on the PC. If another program uses them, the
  script says which, so you can stop it.
- This install keeps its own data and secrets (`.env.home`,
  `secrets\home_*`), separate from the laptop demo (`scripts\demo.cmd`,
  [docs/demo.md](demo.md)) if both are on one PC. Don't run both at once:
  they would both want the database's memory, and only this one uses
  ports 80 and 443.
- The district is fictional ([docs/demo.md](demo.md#the-demo-district)).
  Don't enter real student information on a test PC.
