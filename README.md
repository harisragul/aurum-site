# Aurum AI – free version
GitHub Actions updates the rate twice a day and saves it to the repo; Cloudflare Pages serves the `static` folder. No server, no cost.
Secrets (GitHub repo > Settings > Secrets and variables > Actions): GOLDAPI_KEY, PREMIUM (e.g. 1.08, see below), ANTHROPIC_API_KEY (optional, paid per use; leave out for the free rule-based advisor).
PREMIUM = a Chennai jeweller's board rate / the feed's 24K price per gram. Calibrate once.
Cloudflare Pages: connect the repo, no build command, output directory `static`.
`main.py` + Dockerfile are the always-on server version (needs paid hosting); the free version only uses update.py and static/.
