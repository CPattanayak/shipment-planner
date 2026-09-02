package com.shipmentplanner.model;

import lombok.*;
import jakarta.persistence.*;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

@Entity
@Table(name = "shipments", schema = "shipment")
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class Shipment {

    @Id
    private String id;

    @Column(unique = true, nullable = false)
    private String trackingNumber;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private ShipmentStatus status;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private ShipmentPriority priority;

    @Column(nullable = false)
    private String originWarehouseId;

    // ── Destination address (embedded columns) ────────────────────────────────
    @Column(name = "dest_street")  private String destStreet;
    @Column(name = "dest_city")    private String destCity;
    @Column(name = "dest_state")   private String destState;
    @Column(name = "dest_country") private String destCountry;
    @Column(name = "dest_postal_code") private String destPostalCode;
    @Column(name = "dest_lat", columnDefinition = "NUMERIC(9,6)")  private Double destLat;
    @Column(name = "dest_lng", columnDefinition = "NUMERIC(9,6)")  private Double destLng;

    // ── Totals ────────────────────────────────────────────────────────────────
    @Column(columnDefinition = "NUMERIC(12,3)") private Double totalWeight;
    @Column(columnDefinition = "NUMERIC(12,3)") private Double totalVolume;
    @Column(columnDefinition = "NUMERIC(14,2)") private Double totalValue;

    // ── Assignment ────────────────────────────────────────────────────────────
    private String carrierId;
    private String routeId;

    // ── Timestamps ────────────────────────────────────────────────────────────
    private Instant estimatedDelivery;
    private Instant actualDelivery;
    private Instant scheduledPickup;

    @Column(length = 2000)
    private String specialInstructions;

    @Column(nullable = false, updatable = false)
    private Instant createdAt;

    private Instant updatedAt;

    // ── Relations ─────────────────────────────────────────────────────────────
    @OneToMany(mappedBy = "shipment", cascade = CascadeType.ALL, orphanRemoval = true, fetch = FetchType.EAGER)
    @Builder.Default
    private List<ShipmentItem> items = new ArrayList<>();

    @OneToMany(mappedBy = "shipment", cascade = CascadeType.ALL, orphanRemoval = true, fetch = FetchType.EAGER)
    @OrderBy("timestamp ASC")
    @Builder.Default
    private List<StatusEvent> statusHistory = new ArrayList<>();

    @PrePersist
    protected void onCreate() {
        if (id == null) id = UUID.randomUUID().toString();
        if (trackingNumber == null)
            trackingNumber = "SP-" + id.substring(0, 8).toUpperCase();
        createdAt = Instant.now();
        updatedAt  = Instant.now();
    }

    @PreUpdate
    protected void onUpdate() { updatedAt = Instant.now(); }
}
