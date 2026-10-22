"""Domain models and availability state definitions for See Tickets Resell."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AvailabilityState(str, Enum):
    """Explicit ticket availability states."""

    AVAILABLE = "AVAILABLE"   # Réellement achetable (bouton Ajouter au panier actif)
    IN_CART = "IN_CART"       # Dans le panier d'un autre utilisateur (badge 'dans le panier')
    SOLD_OUT = "SOLD_OUT"     # Épuisé / aucune offre active
    UNKNOWN = "UNKNOWN"       # Erreur HTTP, timeout, réponse inattendue


class TicketModel(BaseModel):
    """Model representing an individual ticket in an advert."""

    id: int
    resale_value_cents: int = Field(default=0)
    purchase_fees_cents: int = Field(default=0)
    product_name: str = Field(default="")

    @property
    def total_price_cents(self) -> int:
        return self.resale_value_cents + self.purchase_fees_cents

    @property
    def total_price_eur(self) -> float:
        return round(self.total_price_cents / 100.0, 2)


class AdvertModel(BaseModel):
    """Model representing an advert listing one or more tickets."""

    id: int
    status: int = Field(default=1)
    dynamic_status: int = Field(default=1)
    nb_available_tickets: int = Field(default=0)
    nb_cart_tickets: int = Field(default=0)
    min_price_cents: int = Field(default=0)
    severability: bool = Field(default=False)
    tickets: List[TicketModel] = Field(default_factory=list)

    @property
    def state(self) -> AvailabilityState:
        """Evaluates whether this advert is truly purchasable, in cart, or sold out."""
        if self.nb_available_tickets <= 0:
            return AvailabilityState.SOLD_OUT

        if self.nb_cart_tickets >= self.nb_available_tickets:
            return AvailabilityState.IN_CART

        # If there are available tickets and not all are held in carts
        if self.nb_cart_tickets == 0 or (self.nb_available_tickets > self.nb_cart_tickets):
            return AvailabilityState.AVAILABLE

        return AvailabilityState.SOLD_OUT

    @property
    def is_purchasable(self) -> bool:
        """True if at least 1 ticket can be added to cart right now."""
        return self.state == AvailabilityState.AVAILABLE

    @property
    def truly_available_count(self) -> int:
        """Number of tickets not held in cart."""
        if self.state == AvailabilityState.AVAILABLE:
            return max(0, self.nb_available_tickets - self.nb_cart_tickets)
        return 0

    @property
    def has_multiple_tickets(self) -> bool:
        """True if 2 or more tickets are truly available."""
        return self.truly_available_count >= 2

    @property
    def price_eur(self) -> float:
        """Price per ticket in EUR (or min price if set)."""
        if self.min_price_cents > 0:
            return round(self.min_price_cents / 100.0, 2)
        if self.tickets:
            return self.tickets[0].total_price_eur
        return 0.0

    @classmethod
    def from_api_dict(cls, data: Dict[str, Any]) -> "AdvertModel":
        """Constructs an AdvertModel from a See Tickets Hydra JSON member."""
        tickets_list = []
        for t in data.get("tickets", []):
            product_dict = t.get("product") or {}
            name_dict = product_dict.get("name") or {}
            # Fallback on English or French string
            product_name = (
                name_dict.get("fr")
                or name_dict.get("en")
                or (str(name_dict) if isinstance(name_dict, str) else "")
            )

            tickets_list.append(
                TicketModel(
                    id=t.get("id", data.get("id", 0)),
                    resale_value_cents=t.get("resaleValue", 0),
                    purchase_fees_cents=t.get("purchaseFees", 0),
                    product_name=product_name,
                )
            )

        return cls(
            id=data.get("id", 0),
            status=data.get("status", 1),
            dynamic_status=data.get("dynamicStatus", 1),
            nb_available_tickets=data.get("nbAvailableTickets", 0),
            nb_cart_tickets=data.get("nbCartTickets", 0),
            min_price_cents=data.get("minPrice", 0),
            severability=data.get("severability", False),
            tickets=tickets_list,
        )


class CategorySummary(BaseModel):
    """Aggregate summary of a category's adverts."""

    category_id: int
    total_items: int = 0
    adverts: List[AdvertModel] = Field(default_factory=list)

    @property
    def available_count(self) -> int:
        return sum(a.truly_available_count for a in self.adverts if a.is_purchasable)

    @property
    def in_cart_count(self) -> int:
        return sum(a.nb_cart_tickets for a in self.adverts if a.state == AvailabilityState.IN_CART)

    @property
    def has_purchasable_tickets(self) -> bool:
        return self.available_count > 0
