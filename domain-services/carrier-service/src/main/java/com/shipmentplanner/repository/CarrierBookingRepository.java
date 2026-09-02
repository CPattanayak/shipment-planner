package com.shipmentplanner.repository;

import com.shipmentplanner.model.CarrierBooking;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface CarrierBookingRepository extends JpaRepository<CarrierBooking, String> {
}
