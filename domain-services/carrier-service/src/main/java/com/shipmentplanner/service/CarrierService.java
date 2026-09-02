package com.shipmentplanner.service;

import com.shipmentplanner.model.Carrier;
import com.shipmentplanner.model.CarrierBooking;
import com.shipmentplanner.repository.CarrierBookingRepository;
import com.shipmentplanner.repository.CarrierRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class CarrierService {

    private final CarrierRepository carrierRepository;
    private final CarrierBookingRepository carrierBookingRepository;

    public Carrier getById(String id) {
        return carrierRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("Carrier not found: " + id));
    }

    public List<Carrier> listAll(Boolean activeOnly) {
        if (Boolean.TRUE.equals(activeOnly)) {
            return carrierRepository.findByActive(true);
        }
        return carrierRepository.findAll();
    }

    public List<Carrier> availableCarriers(Map<String, Object> input) {
        Boolean hasHazardous = (Boolean) input.get("hasHazardous");
        Boolean requiresTemperatureControl = (Boolean) input.get("requiresTemperatureControl");
        Object weightObj = input.get("weightKg");
        Double weightKg = weightObj != null ? ((Number) weightObj).doubleValue() : null;

        List<Carrier> activeCarriers = carrierRepository.findByActive(true);

        return activeCarriers.stream()
                .filter(c -> {
                    if (Boolean.TRUE.equals(hasHazardous) && !Boolean.TRUE.equals(c.getHazardousAllowed())) {
                        return false;
                    }
                    if (Boolean.TRUE.equals(requiresTemperatureControl) && !Boolean.TRUE.equals(c.getTemperatureControlled())) {
                        return false;
                    }
                    if (weightKg != null && c.getMaxWeightKg() != null && weightKg > c.getMaxWeightKg()) {
                        return false;
                    }
                    return true;
                })
                .collect(Collectors.toList());
    }

    public Map<String, Object> getQuote(Map<String, Object> input) {
        String carrierId = (String) input.get("carrierId");
        Object weightObj = input.get("weightKg");
        Double weightKg = weightObj != null ? ((Number) weightObj).doubleValue() : 0.0;
        Object volumeObj = input.get("volumeM3");
        Double volumeM3 = volumeObj != null ? ((Number) volumeObj).doubleValue() : 0.0;
        String serviceLevel = (String) input.get("serviceLevel");

        Carrier carrier = getById(carrierId);

        double costPerKg = 2.5;
        double baseRate = weightKg * costPerKg;
        double fuelSurcharge = baseRate * 0.12;
        double handlingFee = 15.0;
        double totalCost = baseRate + fuelSurcharge + handlingFee;

        int transitDays = 3;
        if ("EXPRESS".equalsIgnoreCase(serviceLevel)) {
            transitDays = 1;
        } else if ("OVERNIGHT".equalsIgnoreCase(serviceLevel)) {
            transitDays = 1;
        } else if ("SAME_DAY".equalsIgnoreCase(serviceLevel)) {
            transitDays = 0;
        }

        String validUntil = OffsetDateTime.now()
                .plusHours(24)
                .format(DateTimeFormatter.ISO_OFFSET_DATE_TIME);

        Map<String, Object> quote = new HashMap<>();
        quote.put("carrierId", carrierId);
        quote.put("carrierName", carrier.getName());
        quote.put("serviceLevel", serviceLevel);
        quote.put("baseRate", baseRate);
        quote.put("fuelSurcharge", fuelSurcharge);
        quote.put("handlingFee", handlingFee);
        quote.put("totalCost", totalCost);
        quote.put("currency", "USD");
        quote.put("transitDays", transitDays);
        quote.put("validUntil", validUntil);

        return quote;
    }

    @Transactional
    public Carrier createCarrier(Map<String, Object> input) {
        Carrier carrier = new Carrier();
        carrier.setId(UUID.randomUUID().toString());
        carrier.setName((String) input.get("name"));
        carrier.setCode((String) input.get("code"));
        carrier.setContactEmail((String) input.get("contactEmail"));
        carrier.setActive(true);
        carrier.setCreatedAt(OffsetDateTime.now());
        carrier.setTotalShipments(0);

        @SuppressWarnings("unchecked")
        List<String> modes = (List<String>) input.get("supportedModes");
        if (modes != null) {
            carrier.setSupportedModes(new HashSet<>(modes));
        }

        @SuppressWarnings("unchecked")
        List<String> areas = (List<String>) input.get("serviceAreas");
        if (areas != null) {
            carrier.setServiceAreas(new HashSet<>(areas));
        }

        return carrierRepository.save(carrier);
    }

    @Transactional
    public Carrier setActive(String id, Boolean active) {
        Carrier carrier = getById(id);
        carrier.setActive(active);
        return carrierRepository.save(carrier);
    }

    @Transactional
    public Map<String, Object> bookCarrier(Map<String, Object> input) {
        String carrierId = (String) input.get("carrierId");
        String shipmentId = (String) input.get("shipmentId");
        String serviceLevel = (String) input.get("serviceLevel");
        String requestedPickupDate = (String) input.get("requestedPickupDate");

        Carrier carrier = getById(carrierId);

        CarrierBooking booking = new CarrierBooking();
        booking.setId(UUID.randomUUID().toString());
        booking.setCarrierId(carrierId);
        booking.setShipmentId(shipmentId);
        booking.setServiceLevel(serviceLevel);
        booking.setConfirmedAt(OffsetDateTime.now());
        booking.setPickupWindow(requestedPickupDate != null ? requestedPickupDate + "/PT4H" : null);
        booking.setEstimatedDelivery(OffsetDateTime.now().plusDays(3));
        booking.setTrackingNumber("TRK-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase());

        CarrierBooking saved = carrierBookingRepository.save(booking);

        Map<String, Object> result = new HashMap<>();
        result.put("bookingId", saved.getId());
        result.put("carrierId", saved.getCarrierId());
        result.put("shipmentId", saved.getShipmentId());
        result.put("confirmedAt", saved.getConfirmedAt() != null
                ? saved.getConfirmedAt().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME) : null);
        result.put("pickupWindow", saved.getPickupWindow());
        result.put("estimatedDelivery", saved.getEstimatedDelivery() != null
                ? saved.getEstimatedDelivery().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME) : null);
        result.put("trackingNumber", saved.getTrackingNumber());
        result.put("serviceLevel", saved.getServiceLevel());

        return result;
    }
}
