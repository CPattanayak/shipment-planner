package com.shipmentplanner.repository;

import com.shipmentplanner.model.DockSlot;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

@Repository
public interface DockSlotRepository extends JpaRepository<DockSlot, String> {

    List<DockSlot> findByWarehouseIdAndDate(String warehouseId, LocalDate date);

    Optional<DockSlot> findById(String id);
}
