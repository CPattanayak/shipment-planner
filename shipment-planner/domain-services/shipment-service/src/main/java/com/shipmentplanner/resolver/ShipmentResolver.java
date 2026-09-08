package com.shipmentplanner.resolver;

import com.shipmentplanner.model.*;
import com.shipmentplanner.service.ShipmentService;
import lombok.RequiredArgsConstructor;
import org.springframework.graphql.data.method.annotation.*;
import org.springframework.stereotype.Controller;

import java.util.List;
import java.util.Map;

@Controller
@RequiredArgsConstructor
public class ShipmentResolver {

    private final ShipmentService service;

    // ── Queries ───────────────────────────────────────────────────────────────

    @QueryMapping
    public Shipment shipment(@Argument String id) { return service.getById(id); }

    @QueryMapping
    public List<Shipment> shipments(
            @Argument ShipmentStatus status,
            @Argument Integer limit,
            @Argument Integer offset) {
        return service.list(status);
    }

    @QueryMapping
    public List<Shipment> shipmentsByOrigin(@Argument String warehouseId) {
        return service.byWarehouse(warehouseId);
    }

    @QueryMapping
    public List<Shipment> shipmentsByCarrier(@Argument String carrierId) {
        return service.byCarrier(carrierId);
    }

    // ── Mutations ─────────────────────────────────────────────────────────────

    @MutationMapping
    public Shipment createShipment(@Argument Map<String, Object> input) {
        return service.create(input);
    }

    @MutationMapping
    public Shipment updateShipmentStatus(
            @Argument String id,
            @Argument ShipmentStatus status,
            @Argument String notes) {
        return service.updateStatus(id, status, notes);
    }

    @MutationMapping
    public Shipment assignCarrier(@Argument String shipmentId, @Argument String carrierId) {
        return service.assignCarrier(shipmentId, carrierId);
    }

    @MutationMapping
    public Shipment assignRoute(@Argument String shipmentId, @Argument String routeId) {
        return service.assignRoute(shipmentId, routeId);
    }

    @MutationMapping
    public Shipment cancelShipment(@Argument String id, @Argument String reason) {
        return service.cancel(id, reason);
    }

    // ── Computed fields ───────────────────────────────────────────────────────

    @SchemaMapping(typeName = "Shipment", field = "destinationAddress")
    public Map<String, Object> destinationAddress(Shipment s) {
        var addr = Map.<String, Object>of(
            "street",     s.getDestStreet() != null ? s.getDestStreet() : "",
            "city",       s.getDestCity() != null ? s.getDestCity() : "",
            "state",      s.getDestState() != null ? s.getDestState() : "",
            "country",    s.getDestCountry() != null ? s.getDestCountry() : "",
            "postalCode", s.getDestPostalCode() != null ? s.getDestPostalCode() : ""
        );
        return addr;
    }
}
