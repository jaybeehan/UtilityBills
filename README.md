# UtilityBills

Logs into Echo Energy (electricity + gas) and City of Lacombe online services (water),
reads the bill history, and adds any missing bills to the **Lacombe Utilities** Google Sheet.
Runs in Container Manager on the Synology, once a day.

The sheet layout is respected: newest bill in row 2, only columns A:D are shifted down,
and the summary formulas in E:I stay put. A bill already in the sheet is matched by date
(within 6 days); if its usage cell is blank, the usage gets filled in.

## Status

| Part | State |
|---|---|
| Google Sheet writer | Done and tested |
| Image build + Container Manager setup | Done |
| Portal logins | Lacombe uses standard DotNetNuke IDs; Echo uses best guesses |
| Bill readers | **Waiting on the capture files** (Part 1) |

---

## Part 1: Capture run (do this now, from your phone)

This logs into both sites once and saves what it sees, so the bill readers can be written.
It only clicks links with words like *bill*, *usage* or *history*, and never anything with
*pay*, *change*, *cancel*, *log out* and similar.

1. **Make the image public (one time).** After the first GitHub build finishes
   (repo → **Actions** tab, green check, a few minutes):
   GitHub → your profile → **Packages** → `utilitybills` → **Package settings** →
   **Change visibility** → **Public**. The image contains no passwords.

2. **Make the folders.** In DS File or File Station, inside the `docker` shared folder,
   create `utility-bills`, and inside that an empty folder named `data`.

3. **Create the project.** DSM → **Container Manager → Project → Create**
   - Project name: `utility-bills`
   - Path: `/docker/utility-bills`
   - Source: **Create docker-compose.yml**, paste in [`docker-compose.yml`](docker-compose.yml)
   - Fill in the four `CHANGE` lines with your Echo and Lacombe logins. Leave `MODE: "capture"`.
   - **Next → Done**. The first download is large (it includes a browser), allow a few minutes.

4. **Wait for it to finish.** Container Manager → **Container** → `utility-bills` → **Log**.
   When you see **CAPTURE FINISHED**, go to **Project → utility-bills → Stop**.
   If you see *still on the login form*, the username or password is wrong, or the site's
   login form needs different settings; send the log text to Claude.

5. **Send the files.** In File Station, go to `docker/utility-bills/data`,
   select the `capture` folder → **Compress** (zip) → download the zip → attach it in the
   Claude chat. From DS File on the phone: long-press the zip → **Download** or **Share**.

   You can look through the `.png` screenshots first to check nothing unexpected is in there.

## Part 2: Google access (after Claude has added the bill readers)

The app writes to your sheet with a Google "service account", a robot account with no
password, that can only touch files you share with it. Easiest from your work computer,
but it works on the phone with the browser in desktop mode.

1. Go to **console.cloud.google.com** → project menu → **New project** → name it `utility-bills`.
2. Search **Google Sheets API** → **Enable**.
3. **IAM & Admin → Service Accounts → Create service account** → name `utility-bills` → **Done**.
4. Tap the new account → **Keys → Add key → Create new key → JSON**. A file downloads.
5. Rename it `service-account.json` and put it in `docker/utility-bills/data` on the NAS.
6. Copy the service account's email (ends in `iam.gserviceaccount.com`). Open the
   Lacombe Utilities sheet → **Share** → paste it → **Editor** → uncheck *Notify* → **Share**.

## Part 3: Test, then switch on

1. **Project → utility-bills → Stop**, then edit the YAML: set `MODE: "once"`, keep
   `DRY_RUN: "true"` → **Save** → **Build**.
2. In the **Log**, check the lines that say what it *would* add.
3. If they look right: edit the YAML again, `MODE: "sync"` and `DRY_RUN: "false"` → **Build**.
   It syncs immediately, then every day at 7 am.

### Updating
When the code changes, GitHub rebuilds the image. Container Manager:
**Project → utility-bills → Action → Build** (Stop first if Build is greyed out).
Your settings and the `data` folder are kept.
