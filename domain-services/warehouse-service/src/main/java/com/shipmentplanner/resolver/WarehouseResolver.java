package com.shipmentplanner.resolver;

import com.shipmentplanner.model.DockSlot;
import com.shipmentplanner.model.Warehouse;
import com.shipmentplanner.service.WarehouseService;
import org.springframework.graphql.data.method.annotation.Argument;
import org.springframework.graphql.data.method.annotation.MutationMapping;
import org.springframework.graphql.data.method.annotation.QueryMapping;
import org.springframework.graphql.data.method.annotation.SchemaMapping;
import org.springframework.stereotype.Controller;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Controller
public class WarehouseResolver {

    private final WarehouseService warehouseService;

    public WarehouseResolver(WarehouseService warehouseService) {
        this.warehouseService = warehouseService;
    }

    // ─── Queries ──────────────────────────────────────────────────────────────

    @QueryMapping
    public Warehouse warehouse(@Argument String id) {
        return warehouseService.getById(id);
    }

    @QueryMapping
    public List<Warehouse> warehouses(@Argument Boolean activeOnly) {
        return warehouseService.listAll(activeOnly);
    }

    @QueryMapping
    public List<DockSlot> availableDockSlots(@Argument String warehouseId,
                                              @Argument String date) {
        return warehouseService.availableDockSlots(warehouseId, date);
    }

    @QueryMapping
    public Map<String, Object> warehouseCapacity(@Argument String id) {
        return warehouseService.warehouseCapacity(id);
    }

    // ─── Mutations ────────────────────────────────────────────────────────────

    @MutationMapping
    public DockSlot bookDockSlot(@Argument Map<String, Object> input) {
        return warehouseService.bookDockSlot(input);
    }

    @MutationMapping
    public DockSlot releaseDockSlot(@Argument String slotId) {
        return warehouseService.releaseDockSlot(slotId);
    }

    @MutationMapping
    public Warehouse updateCapacity(@Argument String warehouseId,
                                    @Argument Double usedM3) {
        return warehouseService.updateCapacity(warehouseId, usedM3);
    }

    // ─── Schema Mappings for Warehouse type ──────────────────────────────────

    @SchemaMapping(typeName = "Warehouse", field = "address")
    public Map<String, Object> address(Warehouse warehouse) {
        Map<String, Object> address = new HashMap<>();
        address.put("street", warehouse.getStreet());
        address.put("city", warehouse.getCity());
        address.put("state", warehouse.getState());
        address.put("country", warehouse.getCountry());
        address.put("postalCode", warehouse.getPostalCode());
        address.put("lat", warehouse.getLat());
        address.put("lng", warehouse.getLng());
        return address;
    }

    @SchemaMapping(typeName = "Warehouse", field = "availableM3")
    public Double availableM3(Warehouse warehouse) {
        return warehouse.getAvailableM3();
    }

    @SchemaMapping(typeName = "Warehouse", field = "utilizationPct")
    public Double utilizationPct(Warehouse warehouse) {
        return warehouse.getUtilizationPct();
    }
}
