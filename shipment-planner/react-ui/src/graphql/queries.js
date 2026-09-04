import { gql } from '@apollo/client';

/* ─── Warehouses ─────────────────────────────────────────────────────────── */

export const GET_WAREHOUSES = gql`
  query GetWarehouses($activeOnly: Boolean = true) {
    warehouses(activeOnly: $activeOnly) {
      id
      code
      name
      capacityM3
      usedM3
      availableM3
      utilizationPct
      active
      capabilities
      address {
        city
        state
        country
        postalCode
      }
    }
  }
`;

export const GET_WAREHOUSE_CAPACITY = gql`
  query GetWarehouseCapacity($id: ID!) {
    warehouseCapacity(id: $id) {
      warehouseId
      totalM3
      usedM3
      availableM3
      utilizationPct
      pendingShipments
    }
  }
`;

export const GET_AVAILABLE_DOCK_SLOTS = gql`
  query GetAvailableDockSlots($warehouseId: ID!, $date: String!) {
    availableDockSlots(warehouseId: $warehouseId, date: $date) {
      id
      dockNumber
      date
      startTime
      endTime
      type
      status
    }
  }
`;

/* ─── Shipments ──────────────────────────────────────────────────────────── */

export const GET_SHIPMENTS = gql`
  query ListShipments($status: ShipmentStatus, $limit: Int = 20, $offset: Int = 0) {
    shipments(status: $status, limit: $limit, offset: $offset) {
      id
      trackingNumber
      status
      priority
      originWarehouseId
      carrierId
      routeId
      totalWeight
      totalVolume
      totalValue
      estimatedDelivery
      createdAt
      destinationAddress {
        city
        state
        country
        postalCode
      }
    }
  }
`;

export const GET_SHIPMENT = gql`
  query GetShipment($id: ID!) {
    shipment(id: $id) {
      id
      trackingNumber
      status
      priority
      originWarehouseId
      carrierId
      routeId
      totalWeight
      totalVolume
      totalValue
      estimatedDelivery
      actualDelivery
      scheduledPickup
      specialInstructions
      createdAt
      updatedAt
      destinationAddress {
        street
        city
        state
        country
        postalCode
      }
      items {
        id
        sku
        description
        quantity
        weight
        volume
        value
        hazardous
        temperatureControlled
        fragile
      }
      statusHistory {
        status
        timestamp
        location
        notes
      }
    }
  }
`;

/* ─── Routes ─────────────────────────────────────────────────────────────── */

export const GET_AVAILABLE_ROUTES = gql`
  query GetAvailableRoutes($originWarehouseId: ID!, $destinationPostalCode: String!) {
    availableRoutes(
      originWarehouseId: $originWarehouseId
      destinationPostalCode: $destinationPostalCode
    ) {
      id
      name
      transportMode
      totalDistanceKm
      estimatedDurationHours
      costPerKg
      maxWeightKg
      maxVolumeM3
      restrictions {
        hazardousAllowed
        temperatureControlled
      }
    }
  }
`;

/* ─── Carriers ───────────────────────────────────────────────────────────── */

export const GET_AVAILABLE_CARRIERS = gql`
  query GetAvailableCarriers(
    $originPostalCode: String!
    $destinationPostalCode: String!
    $weightKg: Float!
    $hasHazardous: Boolean!
    $requiresTemperatureControl: Boolean!
    $serviceLevel: String!
  ) {
    availableCarriers(
      input: {
        originPostalCode: $originPostalCode
        destinationPostalCode: $destinationPostalCode
        weightKg: $weightKg
        hasHazardous: $hasHazardous
        requiresTemperatureControl: $requiresTemperatureControl
        serviceLevel: $serviceLevel
      }
    ) {
      id
      name
      code
      active
      supportedModes
      capabilities {
        maxWeightKg
        maxVolumeM3
        hazardousAllowed
        temperatureControlled
        expressAvailable
        overnightAvailable
        sameDayAvailable
        trackingAvailable
      }
      performance {
        onTimeDeliveryRate
        averageDelayHours
        damageRate
        customerSatisfaction
      }
      contactEmail
    }
  }
`;

export const GET_CARRIER_QUOTE = gql`
  query GetCarrierQuote(
    $carrierId: ID!
    $originPostalCode: String!
    $destinationPostalCode: String!
    $weightKg: Float!
    $volumeM3: Float!
    $serviceLevel: String!
  ) {
    carrierQuote(
      input: {
        carrierId: $carrierId
        originPostalCode: $originPostalCode
        destinationPostalCode: $destinationPostalCode
        weightKg: $weightKg
        volumeM3: $volumeM3
        serviceLevel: $serviceLevel
      }
    ) {
      carrierId
      carrierName
      baseRate
      fuelSurcharge
      handlingFee
      totalCost
      transitDays
      serviceLevel
      validUntil
    }
  }
`;
