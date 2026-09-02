package com.shipmentplanner.model;

import jakarta.persistence.*;
import java.util.UUID;

@Entity
@Table(name = "waypoints", schema = "route")
public class Waypoint {

    @Id
    @Column(name = "id", length = 36)
    private String id;

    // Managed by the parent Route's @JoinColumn — read-only here to avoid write conflict
    @Column(name = "route_id", length = 36, insertable = false, updatable = false)
    private String routeId;

    @Column(name = "sequence", nullable = false)
    private Integer sequence;

    @Column(name = "location", length = 255, nullable = false)
    private String location;

    @Column(name = "lat", columnDefinition = "NUMERIC(9,6)")
    private Double lat;

    @Column(name = "lng", columnDefinition = "NUMERIC(9,6)")
    private Double lng;

    @Column(name = "estimated_arrival", length = 50)
    private String estimatedArrival;

    @Column(name = "type", length = 20, nullable = false)
    private String type;

    @PrePersist
    protected void onCreate() {
        if (id == null) id = UUID.randomUUID().toString();
    }

    public Waypoint() {}

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getRouteId() { return routeId; }
    public void setRouteId(String routeId) { this.routeId = routeId; }

    public Integer getSequence() { return sequence; }
    public void setSequence(Integer sequence) { this.sequence = sequence; }

    public String getLocation() { return location; }
    public void setLocation(String location) { this.location = location; }

    public Double getLat() { return lat; }
    public void setLat(Double lat) { this.lat = lat; }

    public Double getLng() { return lng; }
    public void setLng(Double lng) { this.lng = lng; }

    public String getEstimatedArrival() { return estimatedArrival; }
    public void setEstimatedArrival(String estimatedArrival) { this.estimatedArrival = estimatedArrival; }

    public String getType() { return type; }
    public void setType(String type) { this.type = type; }
}
