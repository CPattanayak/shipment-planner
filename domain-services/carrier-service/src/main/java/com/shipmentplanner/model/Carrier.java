package com.shipmentplanner.model;

import jakarta.persistence.*;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.HashSet;
import java.util.Set;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Entity
@Table(name = "carriers", schema = "carrier")
public class Carrier {

    @Id
    @Column(name = "id", length = 36)
    private String id;

    @Column(name = "name", nullable = false)
    private String name;

    @Column(name = "code", nullable = false, unique = true)
    private String code;

    @Column(name = "active", nullable = false)
    private Boolean active = true;

    @Column(name = "contact_email")
    private String contactEmail;

    @Column(name = "api_endpoint")
    private String apiEndpoint;

    @Column(name = "max_weight_kg", columnDefinition = "NUMERIC(10,2)")
    private Double maxWeightKg;

    @Column(name = "max_volume_m3", columnDefinition = "NUMERIC(10,3)")
    private Double maxVolumeM3;

    @Column(name = "hazardous_allowed")
    private Boolean hazardousAllowed = false;

    @Column(name = "temperature_controlled")
    private Boolean temperatureControlled = false;

    @Column(name = "express_available")
    private Boolean expressAvailable = false;

    @Column(name = "overnight_available")
    private Boolean overnightAvailable = false;

    @Column(name = "same_day_available")
    private Boolean sameDayAvailable = false;

    @Column(name = "tracking_available")
    private Boolean trackingAvailable = false;

    @Column(name = "on_time_delivery_rate", columnDefinition = "NUMERIC(5,4)")
    private Double onTimeDeliveryRate;

    @Column(name = "average_delay_hours", columnDefinition = "NUMERIC(6,2)")
    private Double averageDelayHours;

    @Column(name = "damage_rate", columnDefinition = "NUMERIC(6,5)")
    private Double damageRate;

    @Column(name = "customer_satisfaction", columnDefinition = "NUMERIC(3,2)")
    private Double customerSatisfaction;

    @Column(name = "total_shipments")
    private Integer totalShipments = 0;

    @Column(name = "created_at")
    private OffsetDateTime createdAt;

    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(
        name = "carrier_modes",
        schema = "carrier",
        joinColumns = @JoinColumn(name = "carrier_id")
    )
    @Column(name = "mode")
    private Set<String> supportedModes = new HashSet<>();

    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(
        name = "carrier_service_areas",
        schema = "carrier",
        joinColumns = @JoinColumn(name = "carrier_id")
    )
    @Column(name = "service_area")
    private Set<String> serviceAreas = new HashSet<>();
}
