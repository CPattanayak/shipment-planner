package com.shipmentplanner.repository;

import com.shipmentplanner.model.Route;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface RouteRepository extends JpaRepository<Route, String> {

    List<Route> findByOriginWarehouseIdAndDestinationPostalCode(String originWarehouseId, String destinationPostalCode);

    List<Route> findByOriginWarehouseId(String originWarehouseId);

    List<Route> findByStatus(String status);
}
