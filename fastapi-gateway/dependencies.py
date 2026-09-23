"""
dependencies.py
────────────────
Dependency wiring (DI container).

High-level modules depend on the service abstractions declared here.
Only this file knows which concrete classes satisfy them — Dependency
Inversion Principle applied at the module boundary.

To add a new composite MCP tool:
  1. Create services/my_new_service.py  (business logic)
  2. Add its attribute to CompositeToolRegistry
  3. Wire it inside _build() — nothing else changes.

The CompositeToolRegistry instance is consumed by composite_mcp_server.py,
which turns each service into an @mcp.tool() exposed over HTTP.
FunctionTool / ToolRegistry are no longer needed — everything goes through MCP.
"""

from dataclasses import dataclass

from config import GRAPHQL_ENDPOINT
from repositories.graphql_client import GraphQLClient
from repositories.carrier_repository import CarrierRepository
from repositories.quote_repository import QuoteRepository
from services.carrier_quote_service import CarrierQuoteService


@dataclass(frozen=True)
class CompositeToolRegistry:
    """
    Typed service container for composite MCP tools.

    Each attribute is a service that backs exactly one @mcp.tool() in
    composite_mcp_server.py.  frozen=True prevents accidental mutation.
    """
    carrier_quote: CarrierQuoteService
    # Add more services here as new composite tools are built:
    # warehouse_search: WarehouseSearchService
    # route_compare:    RouteCompareService


def _build() -> CompositeToolRegistry:
    """Wire concrete implementations into the registry."""
    client = GraphQLClient(GRAPHQL_ENDPOINT)

    carrier_repo  = CarrierRepository(client)
    quote_repo    = QuoteRepository(client)
    quote_service = CarrierQuoteService(carrier_repo, quote_repo)

    return CompositeToolRegistry(
        carrier_quote=quote_service,
        # Wire additional services here.
    )


# Module-level singleton — created once at import time.
composite_tool_registry: CompositeToolRegistry = _build()
