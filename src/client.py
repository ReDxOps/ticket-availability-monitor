"""HTTP Client for See Tickets Resell API."""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
import httpx

from src.config import Settings
from src.models import AdvertModel, AvailabilityState

logger = logging.getLogger(__name__)


class SeeTicketsClient:
    """Asynchronous client interacting with See Tickets Resell public APIs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.consecutive_errors: int = 0
        self.backoff_delay: float = 0.0

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
            "Accept": "application/ld+json, application/json, text/plain, */*",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://resell.seetickets.com/dreamnation2026/",
            "Origin": "https://resell.seetickets.com",
            "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        self._client = httpx.AsyncClient(
            http2=True,
            headers=headers,
            timeout=10.0,
            follow_redirects=True,
        )

    async def close(self) -> None:
        """Closes the underlying HTTP client session."""
        await self._client.aclose()

    def _handle_success(self) -> None:
        """Resets error counters on successful response."""
        self.consecutive_errors = 0
        self.backoff_delay = 0.0

    def _handle_error(self, status_code: Optional[int] = None, retry_after: Optional[str] = None) -> None:
        """Updates backoff and error tracking counters."""
        self.consecutive_errors += 1

        if retry_after:
            try:
                self.backoff_delay = max(float(retry_after), 2.0)
                return
            except (ValueError, TypeError):
                pass

        # Exponential backoff: 2s, 4s, 8s, 16s, up to 60s
        self.backoff_delay = min(2.0 ** min(self.consecutive_errors, 6), 60.0)

    async def fetch_adverts(
        self,
        category_id: Optional[int] = None,
    ) -> Tuple[AvailabilityState, List[AdvertModel], Optional[str]]:
        """
        Polls the public adverts_search endpoint for ticket listings.

        Returns:
            Tuple[AvailabilityState, List[AdvertModel], Optional[error_message]]
        """
        target_category = category_id or self.settings.seetickets_category_id
        url = (
            f"{self.settings.seetickets_base_url.rstrip('/')}/api/adverts_search"
            f"?tickets.product.category={target_category}"
            f"&existAvailableTickets=true&status=1"
            f"&orderby[nbCartTickets]=asc&orderby[tickets.resaleValue]=asc"
            f"&page=1&itemsPerPage=9"
        )

        try:
            response = await self._client.get(url)

            if response.status_code == 200:
                self._handle_success()
                try:
                    data = response.json()
                except Exception as ex:
                    self._handle_error(200)
                    return (
                        AvailabilityState.UNKNOWN,
                        [],
                        f"Failed to parse JSON response: {ex}",
                    )

                members = data.get("hydra:member", [])
                total_items = data.get("hydra:totalItems", len(members))

                if total_items == 0 or not members:
                    return AvailabilityState.SOLD_OUT, [], None

                adverts = [AdvertModel.from_api_dict(m) for m in members]

                # Determine overall aggregate state
                if any(a.is_purchasable for a in adverts):
                    overall_state = AvailabilityState.AVAILABLE
                elif any(a.state == AvailabilityState.IN_CART for a in adverts):
                    overall_state = AvailabilityState.IN_CART
                else:
                    overall_state = AvailabilityState.SOLD_OUT

                return overall_state, adverts, None

            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                self._handle_error(429, retry_after)
                logger.warning(
                    f"Rate limited (429) by See Tickets. Backing off for {self.backoff_delay}s."
                )
                return (
                    AvailabilityState.UNKNOWN,
                    [],
                    f"HTTP 429: Rate limited. Retry-After={retry_after}",
                )

            elif response.status_code >= 500:
                self._handle_error(response.status_code)
                logger.error(
                    f"Server error {response.status_code} from See Tickets. Backoff: {self.backoff_delay}s."
                )
                return (
                    AvailabilityState.UNKNOWN,
                    [],
                    f"HTTP {response.status_code}: Server error",
                )

            else:
                self._handle_error(response.status_code)
                logger.warning(f"Unexpected status code {response.status_code} from See Tickets.")
                return (
                    AvailabilityState.UNKNOWN,
                    [],
                    f"HTTP {response.status_code}: Unexpected response",
                )

        except (httpx.TimeoutException, httpx.NetworkError) as ex:
            self._handle_error()
            logger.error(f"Network error querying See Tickets: {ex}")
            return AvailabilityState.UNKNOWN, [], f"Network error: {type(ex).__name__} - {ex}"

        except Exception as ex:
            self._handle_error()
            logger.exception(f"Unexpected exception while querying See Tickets: {ex}")
            return AvailabilityState.UNKNOWN, [], f"Unexpected error: {ex}"

    async def fetch_category_overview(
        self,
        event_id: Optional[int] = None,
    ) -> Dict[int, int]:
        """
        Polls the categories endpoint for the overall event to get ticket counts per category.

        Returns:
            Dict[category_id, nbTicket]
        """
        target_event = event_id or self.settings.seetickets_event_id
        url = f"{self.settings.seetickets_base_url.rstrip('/')}/api/categories?event={target_event}"

        try:
            response = await self._client.get(url)
            if response.status_code == 200:
                data = response.json()
                results: Dict[int, int] = {}
                for cat in data.get("hydra:member", []):
                    cat_id = cat.get("id")
                    if cat_id is not None:
                        results[cat_id] = cat.get("nbTicket", 0)
                return results
        except Exception as ex:
            logger.warning(f"Failed to fetch category overview: {ex}")

        return {}
