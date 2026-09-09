"""
MCP Tool Pipeline Framework
───────────────────────────
Each MCP read tool is a self-contained class that:
  1. Declares what it reads from the shared context  (inputs)
  2. Calls its named MCP tool
  3. Logs: → tool_name  args=...
           ✓ tool_name  → key=value  (success)
           ✗ tool_name  error=...    (failure / no data / GraphQL error)
  4. Writes extracted values back into the shared context

Running the pipeline is one call:
    ctx = ToolContext({"request": req, "weight_kg": ..., ...})
    ok, err = await run_pipeline(ctx, tool_map)

Adding a new tool = one new subclass of MCPToolStep.
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

log = logging.getLogger(__name__)


# ── Context ────────────────────────────────────────────────────────────────────

class ToolContext(dict):
    """
    Shared mutable dict that flows through the pipeline.
    Each step reads inputs from it and writes extracted outputs back.
    """


# ── Base step ─────────────────────────────────────────────────────────────────

class MCPToolStep(ABC):
    """
    Base class for a single MCP tool call in the pipeline.

    Subclasses implement:
      tool_name  — name as registered in the MCP server (e.g. "GetWarehouseCapacity")
      inputs()   — build the args dict from context
      extract()  — pull relevant fields from parsed response data
      validate() — return an error string if extracted data is unusable, else None
    """

    tool_name: str = ""

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _parse(raw) -> dict:
        """Normalise an MCP tool result (str, list-of-content-blocks, or dict) → dict."""
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"_raw_str": raw}
        if isinstance(raw, list):
            # LangChain MCP adapters often return [{"type": "text", "text": "..."}]
            parts = []
            for b in raw:
                if isinstance(b, dict):
                    parts.append(b.get("text", ""))
                elif isinstance(b, str):
                    parts.append(b)
            text = " ".join(p for p in parts if p)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"_raw_list_text": text}
        return raw if isinstance(raw, dict) else {"_raw": str(raw)}

    # ── Subclass interface ─────────────────────────────────────────────────────

    @abstractmethod
    def inputs(self, ctx: ToolContext) -> dict:
        """Return the args dict to pass to the MCP tool."""

    @abstractmethod
    def extract(self, data: dict, ctx: ToolContext) -> dict:
        """
        Given the parsed response `data` dict, return a dict of values
        to merge into the context on success.
        """

    def validate(self, extracted: dict, ctx: ToolContext) -> str | None:
        """
        Return a human-readable error string if `extracted` is unusable;
        return None if everything looks good.
        """
        return None

    # ── Execution ──────────────────────────────────────────────────────────────

    async def run(self, ctx: ToolContext, tool_map: dict) -> tuple[bool, str | None]:
        """
        Execute this step:
          • log inputs
          • call the MCP tool
          • parse and validate the response
          • merge extracted values into ctx on success
          • log the outcome (✓ / ✗)

        Returns (success: bool, error_message: str | None).
        """
        # Guard: tool must be in the map
        if self.tool_name not in tool_map:
            msg = (
                f"{self.tool_name} not found in MCP tool map. "
                f"Available: {list(tool_map.keys())}"
            )
            log.error("✗ %s  %s", self.tool_name, msg)
            return False, msg

        # Build and log inputs
        try:
            args = self.inputs(ctx)
        except KeyError as exc:
            msg = f"{self.tool_name} missing context key {exc} — check pipeline order."
            log.error("✗ %s  %s", self.tool_name, msg)
            return False, msg

        log.info("→ %-30s  args=%s", self.tool_name, args)

        # Call MCP tool
        try:
            raw = await tool_map[self.tool_name].ainvoke(args)
        except Exception as exc:
            msg = f"{self.tool_name} call raised: {exc}"
            log.error("✗ %s  %s", self.tool_name, msg)
            return False, msg

        # Parse response
        parsed = self._parse(raw)
        log.debug("   %s  parsed_keys=%s", self.tool_name, list(parsed.keys()))

        # Surface GraphQL errors
        gql_errors = parsed.get("errors")
        if gql_errors:
            msg = f"{self.tool_name} GraphQL error: {gql_errors}"
            log.error("✗ %s  errors=%s", self.tool_name, gql_errors)
            return False, msg

        # Unwrap {data: {...}} envelope if present
        data = parsed.get("data", parsed)

        # Extract fields
        try:
            extracted = self.extract(data, ctx)
        except Exception as exc:
            msg = f"{self.tool_name} extract() raised: {exc}"
            log.error("✗ %s  %s", self.tool_name, msg)
            return False, msg

        # Validate
        err = self.validate(extracted, ctx)
        if err:
            log.warning(
                "✗ %-30s  %s  (data_keys=%s)",
                self.tool_name, err, list(data.keys()),
            )
            return False, err

        # Success — merge into context
        ctx.update(extracted)

        # Log a tidy summary of what was added
        summary = {
            k: (f"{str(v)[:60]}…" if isinstance(v, str) and len(v) > 60
                else type(v).__name__ if not isinstance(v, (str, int, float, bool))
                else v)
            for k, v in extracted.items()
        }
        log.info("✓ %-30s  → %s", self.tool_name, summary)
        return True, None


# ── Tool steps ─────────────────────────────────────────────────────────────────

class GetWarehouseCapacityStep(MCPToolStep):
    """
    Step 1 — GetWarehouseCapacity
    Input:  id (warehouse ID from request)
    Output: warehouse, capacity, origin_postal
    """
    tool_name = "GetWarehouseCapacity"

    def inputs(self, ctx):
        return {"id": ctx["request"]["originWarehouseId"]}

    def extract(self, data, ctx):
        warehouse     = data.get("warehouse")
        capacity      = data.get("warehouseCapacity", {})
        origin_postal = (warehouse or {}).get("address", {}).get("postalCode", "")
        return {
            "warehouse":    warehouse,
            "capacity":     capacity,
            "origin_postal": origin_postal,
        }

    def validate(self, extracted, ctx):
        if not extracted.get("warehouse"):
            return "warehouse field missing from GetWarehouseCapacity response"
        if not extracted.get("origin_postal"):
            return "warehouse.address.postalCode missing — cannot route without origin postal"
        return None


class OptimizeRouteStep(MCPToolStep):
    """
    Step 2 — OptimizeRoute
    Input:  originWarehouseId, destination postal/country, weightKg, volumeM3
    Output: route, delivery_date
    """
    tool_name = "OptimizeRoute"

    def inputs(self, ctx):
        req = ctx["request"]
        dst = req["destinationAddress"]
        return {
            "originWarehouseId":     req["originWarehouseId"],
            "destinationPostalCode": dst["postalCode"],
            "destinationCountry":    dst.get("country", "US"),
            "weightKg":              ctx["weight_kg"],
            "volumeM3":              ctx["volume_m3"],
        }

    def extract(self, data, ctx):
        route    = data.get("optimizeRoute")
        raw_date = (route or {}).get("estimatedDeliveryDate", "")
        delivery = raw_date[:10] if raw_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {"route": route, "delivery_date": delivery}

    def validate(self, extracted, ctx):
        if not extracted.get("route"):
            return "optimizeRoute field missing — no route returned"
        return None


class GetAvailableCarriersStep(MCPToolStep):
    """
    Step 3 — GetAvailableCarriers
    Input:  origin_postal (from step 1), destination postal, weightKg
    Output: carriers, best_carrier  (max onTimeDeliveryRate)
    """
    tool_name = "GetAvailableCarriers"

    def inputs(self, ctx):
        dst = ctx["request"]["destinationAddress"]
        return {
            "originPostalCode":      ctx["origin_postal"],
            "destinationPostalCode": dst["postalCode"],
            "weightKg":              ctx["weight_kg"],
        }

    def extract(self, data, ctx):
        carriers = data.get("availableCarriers", [])
        best = (
            max(
                carriers,
                key=lambda c: c.get("performance", {}).get("onTimeDeliveryRate", 0),
            )
            if carriers else None
        )
        return {"carriers": carriers, "best_carrier": best}

    def validate(self, extracted, ctx):
        if not extracted.get("carriers"):
            return "availableCarriers is empty — no carriers for this route/weight"
        if not extracted.get("best_carrier"):
            return "could not select best carrier"
        return None


class GetCarrierQuoteStep(MCPToolStep):
    """
    Step 4 — GetCarrierQuote
    Input:  best_carrier.id (from step 3) + origin/dest postal + weight/volume/serviceLevel
    Output: quote
    """
    tool_name = "GetCarrierQuote"

    def inputs(self, ctx):
        dst = ctx["request"]["destinationAddress"]
        return {
            "carrierId":             ctx["best_carrier"]["id"],
            "originPostalCode":      ctx["origin_postal"],
            "destinationPostalCode": dst["postalCode"],
            "weightKg":              ctx["weight_kg"],
            "volumeM3":              ctx["volume_m3"],
            "serviceLevel":          ctx.get("service_level", "STANDARD"),
        }

    def extract(self, data, ctx):
        return {"quote": data.get("carrierQuote")}

    def validate(self, extracted, ctx):
        if not extracted.get("quote"):
            return "carrierQuote field missing — carrier refused to quote"
        return None


# ── Pipeline runner ────────────────────────────────────────────────────────────

PLANNING_STEPS: list[MCPToolStep] = [
    GetWarehouseCapacityStep(),
    OptimizeRouteStep(),
    GetAvailableCarriersStep(),
    GetCarrierQuoteStep(),
]


async def run_planning_pipeline(ctx: ToolContext, tool_map: dict) -> tuple[bool, str | None]:
    """
    Run all PLANNING_STEPS in order.
    Each step reads from ctx and writes back on success.
    Stops and returns (False, error) on the first failure.
    Returns (True, None) when all steps succeed.
    """
    log.info("pipeline start  steps=%s", [s.tool_name for s in PLANNING_STEPS])
    for step in PLANNING_STEPS:
        ok, err = await step.run(ctx, tool_map)
        if not ok:
            log.error("pipeline aborted at %s  error=%s", step.tool_name, err)
            return False, err
    log.info("pipeline complete")
    return True, None
