package com.shipmentplanner.service;

import com.shipmentplanner.model.Route;
import com.shipmentplanner.repository.RouteRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@Transactional
public class RouteService {

    private final RouteRepository routeRepository;

    public RouteService(RouteRepository routeRepository) {
        this.routeRepository = routeRepository;
    }

    @Transactional(readOnly = true)
    public Route getById(String id) {
        return routeRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("Route not found: " + id));
    }

    @Transactional(readOnly = true)
    public List<Route> availableRoutes(String originWarehouseId, String destinationPostalCode) {
        return routeRepository
                .findByOriginWarehouseIdAndDestinationPostalCode(originWarehouseId, destinationPostalCode)
                .stream()
                .filter(r -> "ACTIVE".equals(r.getStatus()))
                .collect(Collectors.toList());
    }

    @Transactional(readOnly = true)
    public Map<String, Object> optimizeRoute(Map<String, Object> input) {
        String originWarehouseId = (String) input.get("originWarehouseId");
        String destinationPostalCode = (String) input.get("destinationPostalCode");
        Double weightKg = toDouble(input.get("weightKg"));

        // Exact match first; fall back to any active route from the same warehouse.
        List<Route> available = availableRoutes(originWarehouseId, destinationPostalCode);
        if (available.isEmpty()) {
            available = routeRepository.findByOriginWarehouseId(originWarehouseId)
                    .stream()
                    .filter(r -> "ACTIVE".equals(r.getStatus()))
                    .collect(Collectors.toList());
        }
        if (available.isEmpty()) {
            throw new RuntimeException(
                    "No routes available from warehouse " + originWarehouseId);
        }

        Route recommended = available.get(0);
        List<Route> alternatives = available.size() > 1 ? available.subList(1, available.size()) : new ArrayList<>();

        double estimatedCost = (weightKg != null ? weightKg : 0.0) * recommended.getCostPerKg();
        double carbonFootprintKg = recommended.getTotalDistanceKm() * 0.21;

        double durationHours = recommended.getEstimatedDurationHours();
        String estimatedDeliveryDate = OffsetDateTime.now()
                .plusSeconds((long) (durationHours * 3600))
                .format(DateTimeFormatter.ISO_OFFSET_DATE_TIME);

        String reasoning = String.format(
                "Selected route '%s' via %s transport mode covering %.1f km in %.1f hours at %.4f per kg.",
                recommended.getName(),
                recommended.getTransportMode(),
                recommended.getTotalDistanceKm(),
                recommended.getEstimatedDurationHours(),
                recommended.getCostPerKg()
        );

        Map<String, Object> result = new HashMap<>();
        result.put("recommendedRoute", recommended);
        result.put("alternatives", alternatives);
        result.put("estimatedCost", estimatedCost);
        result.put("estimatedDeliveryDate", estimatedDeliveryDate);
        result.put("carbonFootprintKg", carbonFootprintKg);
        result.put("reasoning", reasoning);
        return result;
    }

    public Route createRoute(Map<String, Object> input) {
        Route route = new Route();
        route.setId(UUID.randomUUID().toString());
        route.setName((String) input.get("name"));
        route.setOriginWarehouseId((String) input.get("originWarehouseId"));
        route.setDestinationPostalCode((String) input.get("destinationPostalCode"));
        route.setTransportMode((String) input.get("transportMode"));
        route.setTotalDistanceKm(toDouble(input.get("totalDistanceKm")));
        route.setEstimatedDurationHours(toDouble(input.get("estimatedDurationHours")));
        route.setCostPerKg(toDouble(input.get("costPerKg")));
        route.setMaxWeightKg(toDouble(input.get("maxWeightKg")));
        route.setMaxVolumeM3(toDouble(input.get("maxVolumeM3")));
        route.setStatus("ACTIVE");

        @SuppressWarnings("unchecked")
        List<String> carrierIds = (List<String>) input.get("carrierIds");
        if (carrierIds != null) {
            route.getCarrierIds().addAll(carrierIds);
        }

        return routeRepository.save(route);
    }

    public Route setStatus(String id, String status) {
        Route route = getById(id);
        route.setStatus(status);
        return routeRepository.save(route);
    }

    private Double toDouble(Object value) {
        if (value == null) return null;
        if (value instanceof Double) return (Double) value;
        if (value instanceof Number) return ((Number) value).doubleValue();
        return Double.parseDouble(value.toString());
    }
}
