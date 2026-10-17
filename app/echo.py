"""Echo Energy (UTILITYnet) portal: electricity and natural gas."""
from __future__ import annotations

from playwright.sync_api import Page

from portal import Portal


class EchoPortal(Portal):
    name = "echo"
    env_prefix = "ECHO"
    login_url = "https://www.echoenergy.ca/myretailer/portal/index.html"
    # From the captured login page (GWT app; the button is a plain "Go" button).
    user_sel = "#userName"
    pass_sel = "#password"
    submit_sel = "button.gapps-loginButton"

    def read_bills(self, page: Page) -> dict:
        """Return {"electricity": [Bill...], "gas": [Bill...]}.

        Written once the capture files show where the bill history lives.
        """
        return super().read_bills(page)
