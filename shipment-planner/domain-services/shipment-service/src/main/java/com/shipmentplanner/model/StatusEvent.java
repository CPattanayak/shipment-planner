package com.shipmentplanner.model;

import lombok.*;
import jakarta.persistence.*;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "status_events", schema = "shipment")
@Data @Builder @NoArgsConstructor @AllArgsConstructor
public class StatusEvent {
    @Id private String id;

    @Enumerated(EnumType.STRING)
    private ShipmentStatus status;

    private Instant timestamp;
    private String location;

    @Column(length = 1000)
    private String notes;

    @PrePersist
    protected void onCreate() {
        if (id == null) id = UUID.randomUUID().toString();
        if (timestamp == null) timestamp = Instant.now();
    }
}
