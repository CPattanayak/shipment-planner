package com.shipmentplanner.model;

import jakarta.persistence.*;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

@Entity
@Table(name = "routes", schema = "route")
public class Route {

    @Id
    @Column(name = "id", length = 36)
    private String id;

    @Column(name = "name", length = 200, nullable = false)
    private String name;

    @Column(name = "origin_warehouse_id", length = 36, nullable = false)
    private String originWarehouseId;

    @Column(name = "destination_postal_code", length = 20, nullable = false)
    private String destinationPostalCode;

    @Column(name = "status", length = 20, nullable = false)
    private String status = "ACTIVE";

    @Column(name = "transport_mode", length = 20, nullable = false)
    private String transportMode;

    @Column(name = "total_distance_km", columnDefinition = "NUMERIC(10,2)", nullable = false)
    private Double totalDistanceKm;

    @Column(name = "estimated_duration_hours", columnDefinition = "NUMERIC(8,2)", nullable = false)
    private Double estimatedDurationHours;

    @Column(name = "cost_per_kg", columnDefinition = "NUMERIC(10,4)", nullable = false)
    private Double costPerKg;

    @Column(name = "max_weight_kg", columnDefinition = "NUMERIC(10,2)", nullable = false)
    private Double maxWeightKg;

    @Column(name = "max_volume_m3", columnDefinition = "NUMERIC(10,3)", nullable = false)
    private Double maxVolumeM3;

    @Column(name = "hazardous_allowed", nullable = false)
    private Boolean hazardousAllowed = false;

    @Column(name = "temperature_controlled", nullable = false)
    private Boolean temperatureControlled = false;

    @Column(name = "max_item_value_usd", columnDefinition = "NUMERIC(14,2)")
    private Double maxItemValueUsd;

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt;

    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(
        name = "route_countries",
        schema = "route",
        joinColumns = @JoinColumn(name = "route_id")
    )
    @Column(name = "country")
    private Set<String> countries = new HashSet<>();

    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(
        name = "route_carriers",
        schema = "route",
        joinColumns = @JoinColumn(name = "route_id")
    )
    @Column(name = "carrier_id")
    private Set<String> carrierIds = new HashSet<>();

    @OneToMany(cascade = CascadeType.ALL, fetch = FetchType.EAGER, orphanRemoval = true)
    @JoinColumn(name = "route_id")
    @OrderBy("sequence ASC")
    private List<Waypoint> waypoints = new ArrayList<>();

    @PrePersist
    protected void onCreate() {
        if (createdAt == null) {
            createdAt = OffsetDateTime.now();
        }
    }

    public Route() {}

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }

    public String getOriginWarehouseId() { return originWarehouseId; }
    public void setOriginWarehouseId(String originWarehouseId) { this.originWarehouseId = originWarehouseId; }

    public String getDestinationPostalCode() { return destinationPostalCode; }
    public void setDestinationPostalCode(String destinationPostalCode) { this.destinationPostalCode = destinationPostalCode; }

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

    public String getTransportMode() { return transportMode; }
    public void setTransportMode(String transportMode) { this.transportMode = transportMode; }

    public Double getTotalDistanceKm() { return totalDistanceKm; }
    public void setTotalDistanceKm(Double totalDistanceKm) { this.totalDistanceKm = totalDistanceKm; }

    public Double getEstimatedDurationHours() { return estimatedDurationHours; }
    public void setEstimatedDurationHours(Double estimatedDurationHours) { this.estimatedDurationHours = estimatedDurationHours; }

    public Double getCostPerKg() { return costPerKg; }
    public void setCostPerKg(Double costPerKg) { this.costPerKg = costPerKg; }

    public Double getMaxWeightKg() { return maxWeightKg; }
    public void setMaxWeightKg(Double maxWeightKg) { this.maxWeightKg = maxWeightKg; }

    public Double getMaxVolumeM3() { return maxVolumeM3; }
    public void setMaxVolumeM3(Double maxVolumeM3) { this.maxVolumeM3 = maxVolumeM3; }

    public Boolean getHazardousAllowed() { return hazardousAllowed; }
    public void setHazardousAllowed(Boolean hazardousAllowed) { this.hazardousAllowed = hazardousAllowed; }

    public Boolean getTemperatureControlled() { return temperatureControlled; }
    public void setTemperatureControlled(Boolean temperatureControlled) { this.temperatureControlled = temperatureControlled; }

    public Double getMaxItemValueUsd() { return maxItemValueUsd; }
    public void setMaxItemValueUsd(Double maxItemValueUsd) { this.maxItemValueUsd = maxItemValueUsd; }

    public OffsetDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(OffsetDateTime createdAt) { this.createdAt = createdAt; }

    public Set<String> getCountries() { return countries; }
    public void setCountries(Set<String> countries) { this.countries = countries; }

    public Set<String> getCarrierIds() { return carrierIds; }
    public void setCarrierIds(Set<String> carrierIds) { this.carrierIds = carrierIds; }

    public List<Waypoint> getWaypoints() { return waypoints; }
    public void setWaypoints(List<Waypoint> waypoints) { this.waypoints = waypoints; }
}
