package com.shipmentplanner.model;

import lombok.*;
import jakarta.persistence.*;
import java.util.UUID;

@Entity
@Table(name = "shipment_items", schema = "shipment")
@Data @Builder @NoArgsConstructor @AllArgsConstructor
@EqualsAndHashCode(exclude = "shipment")
@ToString(exclude = "shipment")
public class ShipmentItem {
    @Id private String id;
    private String sku;
    private String description;
    private Integer quantity;
    @Column(columnDefinition = "NUMERIC(10,3)") private Double weight;
    @Column(columnDefinition = "NUMERIC(10,3)") private Double volume;
    @Column(columnDefinition = "NUMERIC(12,2)") private Double value;
    private Boolean hazardous;
    private Boolean temperatureControlled;
    private Boolean fragile;

    // Bidirectional back-reference so Hibernate sets shipment_id at INSERT time.
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "shipment_id", nullable = false)
    private Shipment shipment;

    @PrePersist
    protected void onCreate() {
        if (id == null) id = UUID.randomUUID().toString();
    }
}
