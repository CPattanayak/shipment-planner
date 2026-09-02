package com.shipmentplanner.resolver;

import com.shipmentplanner.model.Route;
import com.shipmentplanner.model.Waypoint;
import com.shipmentplanner.service.RouteService;
import org.springframework.graphql.data.method.annotation.Argument;
import org.springframework.graphql.data.method.annotation.MutationMapping;
import org.springframework.graphql.data.method.annotation.QueryMapping;
import org.springframework.graphql.data.method.annotation.SchemaMapping;
import org.springframework.stereotype.Controller;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Controller
public class RouteResolver {

    private final RouteService routeService;

    public RouteResolver(RouteService routeService) {
        this.routeService = routeService;
    }

    // ── Queries ──────────────────────────────────────────────────────────────

    @QueryMapping
    public Route route(@Argument String id) {
        return routeService.getById(id);
    }

    @QueryMapping
    public List<Route> availableRoutes(
            @Argument String originWarehouseId,
            @Argument String destinationPostalCode) {
        return routeService.availableRoutes(originWarehouseId, destinationPostalCode);
    }

    @QueryMapping
    public Map<String, Object> optimizeRoute(@Argument Map<String, Object> input) {
        return routeService.optimizeRoute(input);
    }

    // ── Mutations ─────────────────────────────────────────────────────────────

    @MutationMapping
    public Route createRoute(@Argument Map<String, Object> input) {
        return routeService.createRoute(input);
    }

    @MutationMapping
    public Route setRouteStatus(@Argument String id, @Argument String status) {
        return routeService.setStatus(id, status);
    }

    // ── Schema Mappings ───────────────────────────────────────────────────────

    @SchemaMapping(typeName = "Route", field = "restrictions")
    public Map<String, Object> restrictions(Route route) {
        Map<String, Object> restrictions = new HashMap<>();
        restrictions.put("hazardousAllowed", route.getHazardousAllowed() != null && route.getHazardousAllowed());
        restrictions.put("temperatureControlled", route.getTemperatureControlled() != null && route.getTemperatureControlled());
        restrictions.put("maxItemValueUsd", route.getMaxItemValueUsd());
        restrictions.put("countries", new ArrayList<>(route.getCountries()));
        return restrictions;
    }

    @SchemaMapping(typeName = "Route", field = "waypoints")
    public List<Map<String, Object>> waypoints(Route route) {
        return route.getWaypoints().stream()
                .map(this::waypointToMap)
                .collect(Collectors.toList());
    }

    private Map<String, Object> waypointToMap(Waypoint wp) {
        Map<String, Object> map = new HashMap<>();
        map.put("sequence", wp.getSequence());
        map.put("location", wp.getLocation());
        map.put("lat", wp.getLat());
        map.put("lng", wp.getLng());
        map.put("estimatedArrival", wp.getEstimatedArrival());
        map.put("type", wp.getType());
        return map;
    }
}
