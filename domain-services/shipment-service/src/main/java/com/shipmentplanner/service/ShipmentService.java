package com.shipmentplanner.service;

import com.shipmentplanner.model.*;
import com.shipmentplanner.repository.ShipmentRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class ShipmentService {

    private final ShipmentRepository repo;

    @Transactional
    public Shipment create(Map<String, Object> input) {
        @SuppressWarnings("unchecked")
        Map<String, Object> dest = (Map<String, Object>) input.get("destinationAddress");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> itemInputs = (List<Map<String, Object>>) input.get("items");

        List<ShipmentItem> items = itemInputs.stream().map(i -> ShipmentItem.builder()
            .sku((String) i.get("sku"))
            .description((String) i.get("description"))
            .quantity((Integer) i.get("quantity"))
            .weight(toDouble(i.get("weight")))
            .volume(toDouble(i.get("volume")))
            .value(toDouble(i.get("value")))
            .hazardous(Boolean.TRUE.equals(i.get("hazardous")))
            .temperatureControlled(Boolean.TRUE.equals(i.get("temperatureControlled")))
            .fragile(Boolean.TRUE.equals(i.get("fragile")))
            .build()
        ).collect(Collectors.toList());

        double tw = items.stream().mapToDouble(i -> i.getWeight() * i.getQuantity()).sum();
        double tv = items.stream().mapToDouble(i -> i.getVolume() * i.getQuantity()).sum();
        double tv2 = items.stream().mapToDouble(i -> i.getValue()  * i.getQuantity()).sum();

        StatusEvent created = StatusEvent.builder()
            .status(ShipmentStatus.DRAFT)
            .notes("Shipment created").build();

        Shipment s = Shipment.builder()
            .status(ShipmentStatus.DRAFT)
            .priority(ShipmentPriority.valueOf((String) input.get("priority")))
            .originWarehouseId((String) input.get("originWarehouseId"))
            .destStreet((String) dest.get("street"))
            .destCity((String) dest.get("city"))
            .destState((String) dest.get("state"))
            .destCountry((String) dest.get("country"))
            .destPostalCode((String) dest.get("postalCode"))
            .items(items)
            .totalWeight(tw)
            .totalVolume(tv)
            .totalValue(tv2)
            .specialInstructions((String) input.get("specialInstructions"))
            .statusHistory(new java.util.ArrayList<>(List.of(created)))
            .build();

        if (input.get("scheduledPickup") != null)
            s.setScheduledPickup(Instant.parse((String) input.get("scheduledPickup")));

        // Set bidirectional back-references so Hibernate writes shipment_id at INSERT time.
        s.getItems().forEach(item -> item.setShipment(s));
        s.getStatusHistory().forEach(event -> event.setShipment(s));

        Shipment saved = repo.save(s);
        log.info("Created shipment {}", saved.getTrackingNumber());
        return saved;
    }

    @Transactional
    public Shipment updateStatus(String id, ShipmentStatus status, String notes) {
        Shipment s = getById(id);
        s.setStatus(status);
        StatusEvent ev = StatusEvent.builder().status(status).notes(notes).build();
        ev.setShipment(s);
        s.getStatusHistory().add(ev);
        if (status == ShipmentStatus.DELIVERED) s.setActualDelivery(Instant.now());
        return repo.save(s);
    }

    @Transactional
    public Shipment assignCarrier(String shipmentId, String carrierId) {
        Shipment s = getById(shipmentId);
        s.setCarrierId(carrierId);
        s.setStatus(ShipmentStatus.CARRIER_CONFIRMED);
        StatusEvent ev = StatusEvent.builder()
            .status(ShipmentStatus.CARRIER_CONFIRMED)
            .notes("Carrier " + carrierId + " assigned").build();
        ev.setShipment(s);
        s.getStatusHistory().add(ev);
        return repo.save(s);
    }

    @Transactional
    public Shipment assignRoute(String shipmentId, String routeId) {
        Shipment s = getById(shipmentId);
        s.setRouteId(routeId);
        return repo.save(s);
    }

    @Transactional
    public Shipment cancel(String id, String reason) {
        Shipment s = getById(id);
        s.setStatus(ShipmentStatus.CANCELLED);
        s.getStatusHistory().add(StatusEvent.builder()
            .status(ShipmentStatus.CANCELLED)
            .notes("Cancelled: " + reason).build());
        return repo.save(s);
    }

    public Shipment getById(String id) {
        return repo.findById(id)
            .orElseThrow(() -> new RuntimeException("Shipment not found: " + id));
    }

    public List<Shipment> list(ShipmentStatus status) {
        return status != null ? repo.findByStatus(status) : repo.findAll();
    }

    public List<Shipment> byWarehouse(String id)  { return repo.findByOriginWarehouseId(id); }
    public List<Shipment> byCarrier(String id)     { return repo.findByCarrierId(id); }

    private static double toDouble(Object v) {
        if (v instanceof Number n) return n.doubleValue();
        return 0.0;
    }
}
