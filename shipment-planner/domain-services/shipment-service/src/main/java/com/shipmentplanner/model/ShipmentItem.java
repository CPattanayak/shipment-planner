package com.shipmentplanner.model;

import lombok.*;
import jakarta.persistence.*;
import java.util.UUID;

@Entity
@Table(name = "shipment_items", schema = "shipment")
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class ShipmentItem {
    @Id private String id;
    private String sku;
    private String description;
    private Integer quantity;
    private Double weight;
    private Double volume;
    private Double value;
    private Boolean hazardous;
    private Boolean temperatureControlled;
    private Boolean fragile;

    @PrePersist
    protected void onCreate() {
        if (id == null) id = UUID.randomUUID().toString();
    }
}
