# utility-sync

Logs into Echo Energy (electricity + gas) and City of Lacombe online services (water),
reads the bill history, and adds any missing bills to the **Lacombe Utilities** Google Sheet.
Runs in Docker on the Synology, once a day.

The sheet layout is respected: newest bill in row 2, only columns A:D are shifted down,
and the summary formulas in E:I (including the 12-month averages in I2/I3) stay put.
A bill already in the sheet is matched by date (within 6 days); if its usage cell is blank,
the usage gets filled in.

## Status

| Part | State |
|---|---|
| Google Sheet writer | Done and tested |
| Docker / schedule | Done |
| Portal login | Lacombe uses standard DotNetNuke IDs; Echo uses best guesses |
| Bill parsers | **Waiting on capture files** (step 4) |

## Setup on the Synology

1. **Copy the folder** to the NAS, e.g. `/volume1/docker/utility-sync`, or push it to a
   private GitHub repo and clone it there.

2. **Google service account** (lets the app write to the sheet, no Google password stored):
   - console.cloud.google.com → new project → enable **Google Sheets API**
   - IAM & Admin → Service Accounts → Create → Keys → Add key → JSON
   - Save the file as `data/service-account.json`
   - Open the Lacombe Utilities sheet → Share → add the service account's email
     (ends in `iam.gserviceaccount.com`) as **Editor**

3. **Credentials**: `cp .env.example .env` and fill in both portal logins.
   `.env` and `data/` are git-ignored. Lock them down: `chmod 600 .env`.

4. **Capture run** (logs in once, clicks only bill/usage/history links, never anything
   like Pay, Change, Cancel or Log out):
   ```
   docker compose build
   docker compose run --rm -e MODE=capture utility-sync
   ```
   Results land in `data/capture/echo/` and `data/capture/lacombe/`
   (HTML, screenshots, and any JSON the sites loaded).
   Check the screenshots look right, then zip both folders and send them to Claude.
   Account numbers can be blacked out first; the parser only needs the page structure.

   If login fails, the log says so. Open `00-login.png` / `00-login.html`, find the
   field IDs, and set the `*_SELECTOR` lines in `.env`.

5. **After the parsers are added**, test without writing:
   ```
   docker compose run --rm -e MODE=once -e DRY_RUN=true utility-sync
   ```
   The log lists what it would add. When it looks right, set `DRY_RUN=false` in `.env` and
   ```
   docker compose up -d
   ```
   It syncs immediately, then daily at `RUN_HOUR` (default 7 am). Log: `data/utility-sync.log`.
