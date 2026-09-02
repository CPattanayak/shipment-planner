package com.shipmentplanner.resolver;

import com.shipmentplanner.model.Carrier;
import com.shipmentplanner.service.CarrierService;
import lombok.RequiredArgsConstructor;
import org.springframework.graphql.data.method.annotation.Argument;
import org.springframework.graphql.data.method.annotation.MutationMapping;
import org.springframework.graphql.data.method.annotation.QueryMapping;
import org.springframework.graphql.data.method.annotation.SchemaMapping;
import org.springframework.stereotype.Controller;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Controller
@RequiredArgsConstructor
public class CarrierResolver {

    private final CarrierService carrierService;

    // -------------------------
    // Queries
    // -------------------------

    @QueryMapping
    public Carrier carrier(@Argument String id) {
        return carrierService.getById(id);
    }

    @QueryMapping
    public List<Carrier> carriers(@Argument Boolean activeOnly) {
        return carrierService.listAll(activeOnly);
    }

    @QueryMapping
    public List<Carrier> availableCarriers(@Argument Map<String, Object> input) {
        return carrierService.availableCarriers(input);
    }

    @QueryMapping
    public Map<String, Object> carrierQuote(@Argument Map<String, Object> input) {
        return carrierService.getQuote(input);
    }

    // -------------------------
    // Mutations
    // -------------------------

    @MutationMapping
    public Carrier createCarrier(@Argument Map<String, Object> input) {
        return carrierService.createCarrier(input);
    }

    @MutationMapping
    public Carrier setCarrierActive(@Argument String id, @Argument Boolean active) {
        return carrierService.setActive(id, active);
    }

    @MutationMapping
    public Map<String, Object> bookCarrier(@Argument Map<String, Object> input) {
        return carrierService.bookCarrier(input);
    }

    // -------------------------
    // Schema Mappings
    // -------------------------

    @SchemaMapping(typeName = "Carrier", field = "capabilities")
    public Map<String, Object> capabilities(Carrier carrier) {
        Map<String, Object> caps = new HashMap<>();
        caps.put("supportedModes", carrier.getSupportedModes());
        caps.put("serviceAreas", carrier.getServiceAreas());
        caps.put("maxWeightKg", carrier.getMaxWeightKg());
        caps.put("maxVolumeM3", carrier.getMaxVolumeM3());
        caps.put("hazardousAllowed", carrier.getHazardousAllowed());
        caps.put("temperatureControlled", carrier.getTemperatureControlled());
        caps.put("expressAvailable", carrier.getExpressAvailable());
        caps.put("overnightAvailable", carrier.getOvernightAvailable());
        caps.put("sameDayAvailable", carrier.getSameDayAvailable());
        caps.put("trackingAvailable", carrier.getTrackingAvailable());
        return caps;
    }

    @SchemaMapping(typeName = "Carrier", field = "performance")
    public Map<String, Object> performance(Carrier carrier) {
        Map<String, Object> perf = new HashMap<>();
        perf.put("onTimeDeliveryRate", carrier.getOnTimeDeliveryRate());
        perf.put("averageDelayHours", carrier.getAverageDelayHours());
        perf.put("damageRate", carrier.getDamageRate());
        perf.put("customerSatisfaction", carrier.getCustomerSatisfaction());
        perf.put("totalShipments", carrier.getTotalShipments());
        return perf;
    }
}
