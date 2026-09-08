"""Pydantic request / response models for the FastAPI gateway."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Human-in-the-loop (HITL) ──────────────────────────────────────────────────

class ConfirmationPayload(BaseModel):
    """Describes the mutating tool call that is waiting for approval."""
    tool:      str            # e.g. "CreateShipment"
    arguments: Dict[str, Any]
    summary:   str            # one-line human-readable description
    question:  str            # e.g. "Approve 'CreateShipment'?"


class PlanConfirmRequest(BaseModel):
    """Body for POST /api/v1/plan/confirm."""
    threadId: str
    approved: bool


class PlanConfirmResponse(BaseModel):
    """
    Unified response for POST /api/v1/plan and POST /api/v1/plan/confirm.

    status == "needs_confirmation"
        Agent wants to run a mutating tool; `confirmation` is populated.
        Save `threadId` and POST it to /api/v1/plan/confirm.

    status == "done"
        Agent finished. `agentReasoning` contains the final answer.
    """
    status:         str                          # "needs_confirmation" | "done"
    threadId:       Optional[str] = None
    confirmation:   Optional[ConfirmationPayload] = None   # set when needs_confirmation
    agentReasoning: Optional[str] = None         # set when done
    toolsCalled:    Optional[List[str]] = None   # set when done


# ── Planning request ──────────────────────────────────────────────────────────

class AddressInput(BaseModel):
    street:     Optional[str] = None
    city:       str
    state:      Optional[str] = None
    country:    str
    postalCode: str


class ShipmentItemInput(BaseModel):
    sku:                   str
    description:           str
    quantity:              int   = Field(gt=0)
    weight:                float = Field(gt=0)
    volume:                float = Field(gt=0)
    value:                 float = Field(ge=0)
    hazardous:             bool  = False
    temperatureControlled: bool  = False
    fragile:               bool  = False


class PlanShipmentRequest(BaseModel):
    originWarehouseId:    str
    destinationAddress:   AddressInput
    items:                List[ShipmentItemInput]
    priority:             str            = "STANDARD"
    requiredDeliveryDate: Optional[str]  = None
    specialInstructions:  Optional[str]  = None


# ── Ask / stream ──────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer:       str
    toolsCalled:  List[str]
    messageCount: int


# ── GraphQL pass-through ──────────────────────────────────────────────────────

class GraphQLRequest(BaseModel):
    query:     str
    variables: Optional[Dict[str, Any]] = None


class GraphQLResponse(BaseModel):
    data:   Optional[Dict[str, Any]]
    errors: Optional[List[Dict[str, Any]]] = None
