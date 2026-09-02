package com.shipmentplanner.service;

import com.shipmentplanner.model.DockSlot;
import com.shipmentplanner.model.Warehouse;
import com.shipmentplanner.repository.DockSlotRepository;
import com.shipmentplanner.repository.WarehouseRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@Transactional
public class WarehouseService {

    private final WarehouseRepository warehouseRepository;
    private final DockSlotRepository dockSlotRepository;

    public WarehouseService(WarehouseRepository warehouseRepository,
                            DockSlotRepository dockSlotRepository) {
        this.warehouseRepository = warehouseRepository;
        this.dockSlotRepository = dockSlotRepository;
    }

    @Transactional(readOnly = true)
    public Warehouse getById(String id) {
        return warehouseRepository.findById(id)
            .orElseThrow(() -> new RuntimeException("Warehouse not found: " + id));
    }

    @Transactional(readOnly = true)
    public List<Warehouse> listAll(Boolean activeOnly) {
        if (Boolean.TRUE.equals(activeOnly)) {
            return warehouseRepository.findByActive(true);
        }
        return warehouseRepository.findAll();
    }

    // Default time windows generated when no slots exist for a date.
    private static final List<LocalTime[]> DEFAULT_WINDOWS = Arrays.asList(
        new LocalTime[]{ LocalTime.of( 8, 0), LocalTime.of(10, 0) },
        new LocalTime[]{ LocalTime.of(10, 0), LocalTime.of(12, 0) },
        new LocalTime[]{ LocalTime.of(13, 0), LocalTime.of(15, 0) },
        new LocalTime[]{ LocalTime.of(15, 0), LocalTime.of(17, 0) }
    );
    private static final int DEFAULT_DOCKS = 4;

    /**
     * Returns available dock slots for the given warehouse and date.
     * If no slots exist in the DB, generates and persists a default set
     * (4 docks × 4 time windows) so the agent always sees options.
     */
    @Transactional
    public List<DockSlot> availableDockSlots(String warehouseId, String dateStr) {
        LocalDate date = LocalDate.parse(dateStr);
        List<DockSlot> available = dockSlotRepository.findByWarehouseIdAndDate(warehouseId, date)
            .stream()
            .filter(slot -> "AVAILABLE".equals(slot.getStatus()))
            .collect(Collectors.toList());

        if (!available.isEmpty()) {
            return available;
        }

        // No slots exist — generate default ones and persist them.
        List<DockSlot> generated = new ArrayList<>();
        for (int dock = 1; dock <= DEFAULT_DOCKS; dock++) {
            for (LocalTime[] window : DEFAULT_WINDOWS) {
                DockSlot slot = new DockSlot();
                slot.setId(UUID.randomUUID().toString());
                slot.setWarehouseId(warehouseId);
                slot.setDockNumber(dock);
                slot.setDate(date);
                slot.setStartTime(window[0]);
                slot.setEndTime(window[1]);
                slot.setType("PICKUP");
                slot.setStatus("AVAILABLE");
                generated.add(dockSlotRepository.save(slot));
            }
        }
        return generated;
    }

    @Transactional(readOnly = true)
    public Map<String, Object> warehouseCapacity(String id) {
        Warehouse warehouse = getById(id);
        double totalM3 = warehouse.getCapacityM3() != null ? warehouse.getCapacityM3() : 0.0;
        double usedM3 = warehouse.getUsedM3() != null ? warehouse.getUsedM3() : 0.0;
        double availableM3 = totalM3 - usedM3;
        double utilizationPct = totalM3 > 0 ? (usedM3 / totalM3) * 100.0 : 0.0;

        Map<String, Object> result = new HashMap<>();
        result.put("warehouseId", id);
        result.put("totalM3", totalM3);
        result.put("usedM3", usedM3);
        result.put("availableM3", availableM3);
        result.put("utilizationPct", utilizationPct);
        result.put("pendingShipments", 0);
        return result;
    }

    public DockSlot bookDockSlot(Map<String, Object> input) {
        String warehouseId = (String) input.get("warehouseId");
        int dockNumber = ((Number) input.get("dockNumber")).intValue();
        String dateStr = (String) input.get("date");
        String startTimeStr = (String) input.get("startTime");
        String endTimeStr = (String) input.get("endTime");
        String shipmentId = (String) input.get("shipmentId");
        String type = input.get("type") != null ? input.get("type").toString() : "PICKUP";

        LocalDate date = LocalDate.parse(dateStr);
        LocalTime startTime = LocalTime.parse(startTimeStr);
        LocalTime endTime = LocalTime.parse(endTimeStr);

        // Try to find an existing available slot matching the criteria, otherwise create new
        List<DockSlot> existing = dockSlotRepository.findByWarehouseIdAndDate(warehouseId, date)
            .stream()
            .filter(s -> s.getDockNumber() == dockNumber
                && startTime.equals(s.getStartTime())
                && endTime.equals(s.getEndTime())
                && "AVAILABLE".equals(s.getStatus()))
            .collect(Collectors.toList());

        DockSlot slot;
        if (!existing.isEmpty()) {
            slot = existing.get(0);
        } else {
            slot = new DockSlot();
            slot.setWarehouseId(warehouseId);
            slot.setDockNumber(dockNumber);
            slot.setDate(date);
            slot.setStartTime(startTime);
            slot.setEndTime(endTime);
            slot.setType(type);
        }

        slot.setShipmentId(shipmentId);
        slot.setStatus("BOOKED");
        slot.setType(type);

        return dockSlotRepository.save(slot);
    }

    public DockSlot releaseDockSlot(String slotId) {
        DockSlot slot = dockSlotRepository.findById(slotId)
            .orElseThrow(() -> new RuntimeException("Dock slot not found: " + slotId));
        slot.setStatus("AVAILABLE");
        slot.setShipmentId(null);
        return dockSlotRepository.save(slot);
    }

    public Warehouse updateCapacity(String warehouseId, Double usedM3) {
        Warehouse warehouse = getById(warehouseId);
        warehouse.setUsedM3(usedM3);
        return warehouseRepository.save(warehouse);
    }
}
