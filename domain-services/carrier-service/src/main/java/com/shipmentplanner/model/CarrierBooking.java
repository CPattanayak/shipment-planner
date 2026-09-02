package com.shipmentplanner.model;

import jakarta.persistence.*;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;

import java.time.OffsetDateTime;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Entity
@Table(name = "carrier_bookings", schema = "carrier")
public class CarrierBooking {

    @Id
    @Column(name = "id", length = 36)
    private String id;

    @Column(name = "carrier_id", nullable = false, length = 36)
    private String carrierId;

    @Column(name = "shipment_id", nullable = false, length = 36)
    private String shipmentId;

    @Column(name = "confirmed_at")
    private OffsetDateTime confirmedAt;

    @Column(name = "pickup_window")
    private String pickupWindow;

    @Column(name = "estimated_delivery")
    private OffsetDateTime estimatedDelivery;

    @Column(name = "tracking_number")
    private String trackingNumber;

    @Column(name = "service_level")
    private String serviceLevel;
}
