package com.shipmentplanner.model;

import jakarta.persistence.*;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "warehouses", schema = "warehouse")
public class Warehouse {

    @Id
    @Column(name = "id", length = 36)
    private String id;

    @Column(name = "code", unique = true, nullable = false)
    private String code;

    @Column(name = "name", nullable = false)
    private String name;

    @Column(name = "street")
    private String street;

    @Column(name = "city", nullable = false)
    private String city;

    @Column(name = "state")
    private String state;

    @Column(name = "country", nullable = false)
    private String country;

    @Column(name = "postal_code", nullable = false)
    private String postalCode;

    @Column(name = "lat", columnDefinition = "NUMERIC(9,6)")
    private Double lat;

    @Column(name = "lng", columnDefinition = "NUMERIC(9,6)")
    private Double lng;

    @Column(name = "capacity_m3", nullable = false, columnDefinition = "NUMERIC(12,3)")
    private Double capacityM3;

    @Column(name = "used_m3", columnDefinition = "NUMERIC(12,3)")
    private Double usedM3;

    @Column(name = "active")
    private Boolean active;

    @Column(name = "contact_email")
    private String contactEmail;

    @Column(name = "contact_phone")
    private String contactPhone;

    @Column(name = "created_at")
    private OffsetDateTime createdAt;

    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(
        name = "warehouse_capabilities",
        schema = "warehouse",
        joinColumns = @JoinColumn(name = "warehouse_id")
    )
    @Column(name = "capability")
    private List<String> capabilities = new ArrayList<>();

    @PrePersist
    public void prePersist() {
        if (id == null) {
            id = java.util.UUID.randomUUID().toString();
        }
        if (usedM3 == null) {
            usedM3 = 0.0;
        }
        if (active == null) {
            active = true;
        }
        if (createdAt == null) {
            createdAt = OffsetDateTime.now();
        }
    }

    @Transient
    public Double getAvailableM3() {
        if (capacityM3 == null) return 0.0;
        double used = usedM3 == null ? 0.0 : usedM3;
        return capacityM3 - used;
    }

    @Transient
    public Double getUtilizationPct() {
        if (capacityM3 == null || capacityM3 == 0.0) return 0.0;
        double used = usedM3 == null ? 0.0 : usedM3;
        return (used / capacityM3) * 100.0;
    }

    // Getters and setters

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getCode() { return code; }
    public void setCode(String code) { this.code = code; }

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }

    public String getStreet() { return street; }
    public void setStreet(String street) { this.street = street; }

    public String getCity() { return city; }
    public void setCity(String city) { this.city = city; }

    public String getState() { return state; }
    public void setState(String state) { this.state = state; }

    public String getCountry() { return country; }
    public void setCountry(String country) { this.country = country; }

    public String getPostalCode() { return postalCode; }
    public void setPostalCode(String postalCode) { this.postalCode = postalCode; }

    public Double getLat() { return lat; }
    public void setLat(Double lat) { this.lat = lat; }

    public Double getLng() { return lng; }
    public void setLng(Double lng) { this.lng = lng; }

    public Double getCapacityM3() { return capacityM3; }
    public void setCapacityM3(Double capacityM3) { this.capacityM3 = capacityM3; }

    public Double getUsedM3() { return usedM3; }
    public void setUsedM3(Double usedM3) { this.usedM3 = usedM3; }

    public Boolean getActive() { return active; }
    public void setActive(Boolean active) { this.active = active; }

    public String getContactEmail() { return contactEmail; }
    public void setContactEmail(String contactEmail) { this.contactEmail = contactEmail; }

    public String getContactPhone() { return contactPhone; }
    public void setContactPhone(String contactPhone) { this.contactPhone = contactPhone; }

    public OffsetDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(OffsetDateTime createdAt) { this.createdAt = createdAt; }

    public List<String> getCapabilities() { return capabilities; }
    public void setCapabilities(List<String> capabilities) { this.capabilities = capabilities; }
}
