"""Echo Energy (UTILITYnet) portal: electricity and natural gas."""
from __future__ import annotations

from playwright.sync_api import Page

from portal import Portal


class EchoPortal(Portal):
    name = "echo"
    env_prefix = "ECHO"
    login_url = "https://www.echoenergy.ca/myretailer/portal/index.html"
    # Best guesses until the capture shows the real form; override in .env if login fails.
    user_sel = "input[type=email], input[name*=user i], input[id*=user i], input[name*=email i]"
    pass_sel = "input[type=password]"
    submit_sel = "button[type=submit], input[type=submit], button:has-text('Log')"

    def read_bills(self, page: Page) -> dict:
        """Return {"electricity": [Bill...], "gas": [Bill...]}.

        Written once the capture files show where the bill history lives.
        """
        return super().read_bills(page)
