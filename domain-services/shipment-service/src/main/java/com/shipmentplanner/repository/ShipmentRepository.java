package com.shipmentplanner.repository;

import com.shipmentplanner.model.Shipment;
import com.shipmentplanner.model.ShipmentStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface ShipmentRepository extends JpaRepository<Shipment, String> {
    List<Shipment> findByStatus(ShipmentStatus status);
    List<Shipment> findByOriginWarehouseId(String warehouseId);
    List<Shipment> findByCarrierId(String carrierId);
}
