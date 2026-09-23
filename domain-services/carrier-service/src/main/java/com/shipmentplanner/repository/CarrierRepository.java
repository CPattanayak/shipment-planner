package com.shipmentplanner.repository;

import com.shipmentplanner.model.Carrier;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface CarrierRepository extends JpaRepository<Carrier, String> {

    List<Carrier> findByActive(Boolean active);

    /** Look up a carrier by its short code (e.g. "SRC", "UPS"). */
    Optional<Carrier> findByCode(String code);

    /**
     * Case-insensitive name lookup.
     * Spring Data JPA derives the query automatically — no SQL needed.
     * Used by {@code getQuoteByName} to resolve a human-readable carrier
     * name (e.g. "FastFreight USA") to its entity without requiring the
     * caller to know the database ID.
     */
    Optional<Carrier> findByNameIgnoreCase(String name);
}
