"""City of Lacombe online services (Vadim / DotNetNuke): water, sewer, garbage."""
from __future__ import annotations

from playwright.sync_api import Page

from portal import Portal


class LacombePortal(Portal):
    name = "lacombe"
    env_prefix = "LACOMBE"
    login_url = "https://onlineservices.lacombe.ca/login.aspx"
    # Standard DotNetNuke login control IDs; override in .env if the city customised them.
    user_sel = "input[id$='txtUsername']"
    pass_sel = "input[id$='txtPassword']"
    submit_sel = "a[id$='cmdLogin'], input[id$='cmdLogin']"
    # Both "Utility Billing" links from the logged-in home page.
    start_urls = (
        "https://onlineservices.lacombe.ca/vadimopen/LinkClick.aspx?link=86&tabid=55&portalid=0&mid=421",
        "https://onlineservices.lacombe.ca/OnlineServices/UtilityBilling.aspx",
    )

    def read_bills(self, page: Page) -> dict:
        """Return {"water": [Bill...]}.

        Written once the capture files show the Utility Billing history page.
        """
        return super().read_bills(page)
