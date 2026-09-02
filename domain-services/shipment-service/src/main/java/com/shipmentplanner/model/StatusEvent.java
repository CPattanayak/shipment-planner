package com.shipmentplanner.model;

import lombok.*;
import jakarta.persistence.*;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "status_events", schema = "shipment")
@Data @Builder @NoArgsConstructor @AllArgsConstructor
@EqualsAndHashCode(exclude = "shipment")
@ToString(exclude = "shipment")
public class StatusEvent {
    @Id private String id;

    @Enumerated(EnumType.STRING)
    private ShipmentStatus status;

    private Instant timestamp;
    private String location;

    @Column(length = 1000)
    private String notes;

    // Bidirectional back-reference so Hibernate sets shipment_id at INSERT time.
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "shipment_id", nullable = false)
    private Shipment shipment;

    @PrePersist
    protected void onCreate() {
        if (id == null) id = UUID.randomUUID().toString();
        if (timestamp == null) timestamp = Instant.now();
    }
}
