# 🚚 Shipment Planner Engine — Complete Guide

> **For anyone reading this:** You do not need to be a developer to understand this document.  
> Every concept is explained in plain English first, then the technical detail follows.

---

## 📖 Table of Contents

1. [What does this system do?](#1-what-does-this-system-do)
2. [The Big Picture — How it all fits together](#2-the-big-picture)
3. [Technology explained in plain English](#3-technology-explained-in-plain-english)
4. [Project folder structure](#4-project-folder-structure)
5. [Setup — Step by step](#5-setup--step-by-step)
6. [Real examples you can run right now](#6-real-examples-you-can-run-right-now)
7. [Switching the AI model](#7-switching-the-ai-model)
8. [Common errors and fixes](#8-common-errors-and-fixes)
9. [Developer reference](#9-developer-reference)

---

## 1. What does this system do?

Imagine you work at a company that ships boxes from warehouses to customers.  
Every day you need to answer questions like:

- *"Which truck company (carrier) is cheapest for this heavy package?"*
- *"Does our Chicago warehouse have space to process this order?"*
- *"What is the fastest route to deliver to New York by Friday?"*
- *"Can we ship these chemicals safely?"*

Normally a human logistics expert would look at spreadsheets, call carriers, check maps, and piece the answer together manually. **This system does all of that automatically using AI.**

You send a plain-English question like:

> *"Plan a shipment of 50 laptops from Chicago warehouse to New York, we need it by Thursday, pick the cheapest carrier"*

The AI thinks, checks the live data (warehouse capacity, available routes, carrier prices), and replies with a complete shipment plan — route chosen, carrier booked, tracking number generated.

---

## 2. The Big Picture

Here is what happens when you send a question, step by step:

```
You (or your app)
        │
        │  "Plan a shipment of 50 laptops..."
        ▼
┌──────────────────────────────────────────────────────┐
│            FASTAPI GATEWAY  (port 8000)              │
│                                                      │
│   This is the front door. Every request comes here.  │
│   It has a Swagger page so you can test it visually. │
└──────────────────────┬───────────────────────────────┘
                       │
                       │  Passes your question to the AI Agent
                       ▼
┌──────────────────────────────────────────────────────┐
│           LANGGRAPH AGENT  (inside the gateway)      │
│                                                      │
│   Think of this as a very smart assistant who reads  │
│   your question, figures out which tools to use,     │
│   calls them in the right order, and writes a        │
│   summary back to you.                               │
│                                                      │
│   The brain (LLM) is powered by OpenRouter —        │
│   you can pick any AI model you like.               │
└──────────────────────┬───────────────────────────────┘
                       │
                       │  Calls tools via MCP protocol
                       ▼
┌──────────────────────────────────────────────────────┐
│         APOLLO MCP SERVER  (port 8090)               │
│                                                      │
│   MCP = Model Context Protocol.                      │
│   Think of it as a "tool shop" the AI can browse.    │
│   Each .graphql file in operations/ = one MCP tool.  │
│   It translates tool calls into GraphQL and forwards │
│   them to the Apollo Router — no custom code needed. │
│                                                      │
│   Official image: ghcr.io/apollographql/            │
│                   apollo-mcp-server                  │
└──────────────────────┬───────────────────────────────┘
                       │
                       │  GraphQL queries
                       ▼
┌──────────────────────────────────────────────────────┐
│          APOLLO ROUTER  (port 4000)                  │
│                                                      │
│   Think of this as a post office switchboard.        │
│   It receives every data request and routes it to    │
│   the right department (domain service).             │
└──────┬──────────┬─────────────┬──────────────┬───────┘
       │          │             │              │
       ▼          ▼             ▼              ▼
  SHIPMENT    ROUTE         CARRIER       WAREHOUSE
  SERVICE     SERVICE       SERVICE       SERVICE
  :8081       :8082         :8083         :8084
  
  "Does this   "What is      "Which truck  "Is there
  shipment     the best      company can   space in
  exist?"      road to NY?"  do this?"     Chicago?"

       │          │             │              │
       └──────────┴─────────────┴──────────────┘
                       │
                       ▼
            ┌─────────────────────┐
            │    POSTGRESQL DB    │
            │   (single database, │
            │   4 separate areas) │
            │                     │
            │  shipment schema    │
            │  route schema       │
            │  carrier schema     │
            │  warehouse schema   │
            └─────────────────────┘
```

### The flow in one sentence per step

| Step | What happens |
|------|-------------|
| 1 | You call the FastAPI Gateway with your question |
| 2 | LangGraph Agent reads it and makes a plan |
| 3 | Agent calls MCP tools via JSON-RPC (e.g. "check warehouse capacity") |
| 4 | **Apollo MCP Server** maps the tool call to a named `.graphql` operation |
| 5 | It forwards the query to Apollo Router (no custom code — just .graphql files!) |
| 6 | Apollo Router sends it to the right Spring Boot service |
| 7 | Spring Boot service reads/writes PostgreSQL |
| 8 | Answer flows back up the chain |
| 9 | Agent repeats steps 3–8 as many times as needed |
| 10 | Agent writes a final human-readable answer |
| 11 | FastAPI Gateway returns it to you |

---

## 3. Technology explained in plain English

### 🤖 LangGraph
An AI workflow engine. It lets you define a *graph* of steps: the AI thinks → calls a tool → gets result → thinks again → calls another tool → writes answer. This back-and-forth loop continues until the AI has everything it needs.

**Analogy:** A junior analyst who knows which databases to query. You give them a task, they run several searches, and bring back a report.

---

### 🛠 MCP (Model Context Protocol) — Official Apollo MCP Server
A standard way for AI models to discover and call tools. The **official Apollo MCP Server** (`ghcr.io/apollographql/apollo-mcp-server`) publishes a list of tools automatically from `.graphql` files: *"Here are 15 things you can do: GetShipment, ListShipments, OptimizeRoute..."* Each file is one tool — **no Python, no custom server code**.

**How it works:**
1. You drop a `.graphql` file into `apollo-mcp-server/operations/` (e.g. `GetShipment.graphql`)
2. The server hot-reloads and immediately exposes it as a new MCP tool
3. The AI agent discovers it on the next request — zero restarts needed

**Analogy:** A restaurant menu that updates the moment the chef writes a new dish on a slip of paper — no reprinting required.

---

### 📡 Apollo Federation + GraphQL
Your four Spring Boot services each speak GraphQL. Apollo Federation stitches them together into *one single API* so the AI (or any client) doesn't need to know there are four separate services — it just asks one question and the router figures out where to get each piece of data.

**Analogy:** A company receptionist. You ask "Can I speak to someone about my order AND check my delivery date?" The receptionist silently connects you to Shipping AND Tracking and merges the answer.

---

### 🌐 OpenRouter
A service that lets you access many different AI models (Claude, GPT-4, Llama, Gemini, etc.) through a single standard API. You just change one line in your config to switch models — no code changes needed.

**Analogy:** A universal remote control for AI models.

---

### 🍃 Spring Boot (Java)
The four domain services are written in Spring Boot — a popular Java framework. Each service owns one area of the business: Shipments, Routes, Carriers, or Warehouses.

**Analogy:** Four separate departments in a company. Each has its own filing system (database schema) and its own staff (Java code).

---

### 🐘 PostgreSQL (one database, four schemas)
All data lives in one PostgreSQL database, but divided into four isolated areas called *schemas*. Each Spring Boot service can only see its own schema — they cannot accidentally overwrite each other's data.

**Analogy:** One office building (the database) with four locked offices (schemas). Each team has the key only to their own office.

---

### ⚡ FastAPI
A Python web framework for building APIs quickly. This is your main entry point — it has a built-in documentation page (Swagger UI) where you can click buttons to test every endpoint without writing any code.

**Analogy:** The reception desk of the whole system. All visitors (requests) come here first.

---

## 4. Project Folder Structure

```
shipment-planner/
│
├── pom.xml                     ← THE PARENT POM. Open THIS in your IDE.
│                                  All 4 Java services load automatically.
│
├── docker-compose.yml          ← Start the whole system with one command.
├── .env.example                ← Copy to .env and add your API key.
├── README.md                   ← This file.
│
├── domain-services/            ← The 4 Spring Boot Java services
│   │
│   ├── shipment-service/       ← Manages shipment records & status
│   │   ├── pom.xml             ← Inherits from parent pom.xml
│   │   ├── Dockerfile
│   │   └── src/main/
│   │       ├── java/com/shipmentplanner/
│   │       │   ├── model/      ← Java classes (Shipment, ShipmentItem...)
│   │       │   ├── repository/ ← Database access (JPA)
│   │       │   ├── service/    ← Business logic
│   │       │   └── resolver/   ← GraphQL entry points (like controllers)
│   │       └── resources/
│   │           ├── application.yml        ← Config (DB url, port...)
│   │           ├── graphql/shipment.graphqls ← GraphQL schema
│   │           └── db/migration/V1__*.sql    ← Creates the DB tables
│   │
│   ├── route-service/          ← Route optimization (cheapest/fastest path)
│   ├── carrier-service/        ← Carrier management & booking
│   └── warehouse-service/      ← Warehouse capacity & dock scheduling
│
├── apollo-federation/
│   ├── supergraph.yaml         ← Tells Rover how to combine the 4 GraphQL services
│   └── router.yaml             ← Apollo Router config (ports, CORS, etc.)
│
├── apollo-mcp-server/          ← Official Apollo MCP Server (NO custom code!)
│   ├── config.yaml             ← Tells the server where operations & schema live
│   └── operations/             ← One .graphql file = one MCP tool (hot-reloaded)
│       ├── GetShipment.graphql
│       ├── ListShipments.graphql
│       ├── CreateShipment.graphql
│       ├── UpdateShipmentStatus.graphql
│       ├── AssignCarrier.graphql
│       ├── AssignRoute.graphql
│       ├── GetWarehouses.graphql
│       ├── GetWarehouseCapacity.graphql
│       ├── GetAvailableDockSlots.graphql
│       ├── BookDockSlot.graphql
│       ├── GetAvailableRoutes.graphql
│       ├── OptimizeRoute.graphql
│       ├── GetAvailableCarriers.graphql
│       ├── GetCarrierQuote.graphql
│       └── BookCarrier.graphql
│
├── fastapi-gateway/            ← Python: AI gateway (LangGraph + OpenRouter)
│   ├── main.py                 ← FastAPI app with all REST endpoints
│   ├── agent.py                ← LangGraph graph (the AI brain)
│   ├── mcp_client.py           ← Calls tools on the MCP server
│   ├── models.py               ← Request/response shapes (Pydantic)
│   └── config.py               ← Reads OpenRouter key & URLs from .env
│
└── docker/
    └── postgres-init/
        └── 00_create_schemas.sql  ← Creates the 4 schemas and 4 users in Postgres
```

---

## 5. Setup — Step by Step

### What you need installed

| Tool | What it is | Download |
|------|-----------|---------|
| Docker Desktop | Runs everything in containers | https://docker.com/products/docker-desktop |
| JDK 17 | Java compiler | https://adoptium.net |
| Maven 3.9+ | Java build tool | https://maven.apache.org/download.cgi |
| Node.js 18+ | Needed for Rover (Apollo CLI) | https://nodejs.org |

Verify each is installed:
```bash
docker --version        # Docker version 24.x...
java -version           # openjdk version "17.x..."
mvn -version            # Apache Maven 3.9...
node --version          # v18.x...
```

---

### Step 1 — Get your OpenRouter API key

1. Go to **https://openrouter.ai** and create a free account
2. Click **Keys** → **Create Key**
3. Copy the key (it starts with `sk-or-v1-...`)

> **Free models available!** You don't need to pay. Set `OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct` for a free model.

---

### Step 2 — Configure the project

```bash
# In the shipment-planner folder:
cp .env.example .env
```

Open `.env` in any text editor (Notepad, VS Code, etc.) and fill in:

```env
OPENROUTER_API_KEY=sk-or-v1-YOUR_KEY_HERE

# Pick any model. Free options:
OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct

# Paid but powerful:
# OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
# OPENROUTER_MODEL=openai/gpt-4o
```

---

### Step 3 — Build the Java services

```bash
# Run this once from the shipment-planner/ root folder
mvn clean package -DskipTests
```

You will see Maven download dependencies and compile all 4 services. Expected output at the end:
```
[INFO] BUILD SUCCESS
[INFO] Total time: 45 seconds
```

---

### Step 4 — Generate the Apollo Supergraph schema

This step combines the 4 GraphQL schemas into one. Do it once, or whenever you change a `.graphqls` file.

```bash
# Install the Rover CLI tool (one-time)
npm install -g @apollo/rover

# Start only the database and the 4 Spring Boot services
docker-compose up -d postgres shipment-service route-service carrier-service warehouse-service

# Wait ~20 seconds for them to start, then run:
cd apollo-federation
rover supergraph compose --config supergraph.yaml > supergraph.graphql
cd ..
```

You should see:
```
 COMPOSED  Successfully composed into supergraph.graphql
```

---

### Step 5 — Start everything

```bash
docker-compose up --build
```

First run takes 3–5 minutes (downloads base images, builds containers).  
After that: `docker-compose up` takes ~30 seconds.

When you see these lines, everything is ready:
```
sp-shipment  | Started ShipmentServiceApplication in 4.2 seconds
sp-route     | Started RouteApplication in 3.8 seconds
sp-carrier   | Started CarrierApplication in 3.9 seconds
sp-warehouse | Started WarehouseApplication in 4.1 seconds
sp-router    | GraphQL server is running on port 4000
sp-mcp       | Apollo MCP Server listening on 0.0.0.0:8000
sp-gateway   | Uvicorn running on http://0.0.0.0:8000
```

---

### Step 6 — Open the documentation

Open your browser and go to:

| What | URL | What you can do |
|------|-----|----------------|
| **Main API Docs (Swagger)** | http://localhost:8000/docs | Test all endpoints visually |
| **Apollo Sandbox (GraphQL explorer)** | http://localhost:4000 | Write raw GraphQL queries |
| **MCP Tool List** | http://localhost:8000/api/v1/tools | See all AI tools (via gateway) |
| **Shipment GraphiQL** | http://localhost:8081/graphiql | Explore shipment data directly |

---

## 6. Real Examples You Can Run Right Now

### Using Swagger UI (no coding needed)

1. Go to **http://localhost:8000/docs**
2. Click any endpoint to expand it
3. Click **"Try it out"**
4. Fill in the values and click **"Execute"**

---

### Example A — Ask a simple question

**What you send:**
```
POST http://localhost:8000/api/v1/ask
```
```json
{
  "question": "What warehouses do we have and how full are they?"
}
```

**What happens behind the scenes:**
1. LangGraph agent reads your question
2. Decides to call the `get_warehouses` MCP tool
3. MCP server sends a GraphQL query to Apollo Router
4. Apollo Router forwards it to Warehouse Service
5. Warehouse Service queries PostgreSQL `warehouse` schema
6. Data flows back up, agent writes a summary

**What you get back:**
```json
{
  "answer": "We currently have 3 active warehouses:\n\n1. **Chicago Central (CHI-01)** — 50,000 m³ total capacity, currently 0% utilized (brand new, no shipments yet)\n2. **New York East (NYC-01)** — 35,000 m³ total capacity, 0% utilized\n3. **Los Angeles West (LAX-01)** — 45,000 m³ total capacity, 0% utilized\n\nAll warehouses have plenty of available space.",
  "toolsCalled": ["get_warehouses"],
  "messageCount": 3
}
```

---

### Example B — Plan a full shipment

**What you send:**
```
POST http://localhost:8000/api/v1/plan
```
```json
{
  "originWarehouseId": "wh-001",
  "destinationAddress": {
    "city": "New York",
    "state": "NY",
    "country": "US",
    "postalCode": "10001"
  },
  "items": [
    {
      "sku": "LAPTOP-PRO-15",
      "description": "Professional Laptop 15 inch",
      "quantity": 50,
      "weight": 2.5,
      "volume": 0.005,
      "value": 1200.00,
      "hazardous": false,
      "temperatureControlled": false,
      "fragile": true
    }
  ],
  "priority": "EXPRESS",
  "requiredDeliveryDate": "2026-09-05",
  "specialInstructions": "Handle with care - fragile electronics"
}
```

**What the AI agent does step by step:**

```
Step 1: Check warehouse capacity at wh-001
        → Tool: get_warehouse_capacity
        → Result: 50,000 m³ available ✓

Step 2: Find available routes Chicago → 10001
        → Tool: optimize_route
        → Result: Road route (1,200 km, 18 hrs) wins for EXPRESS
        
Step 3: Find carriers that can handle 125 kg, fragile, no hazardous
        → Tool: get_available_carriers
        → Result: [FedEx Express, UPS Next Day, DHL Express]

Step 4: Get quotes from each carrier
        → Tool: get_carrier_quote (×3)
        → FedEx: $387.50 | UPS: $412.00 | DHL: $395.00

Step 5: Create the shipment record
        → Tool: create_shipment
        → Tracking: SP-A1B2C3D4

Step 6: Assign best carrier (FedEx - cheapest for EXPRESS)
        → Tool: assign_carrier_to_shipment

Step 7: Assign the optimal route
        → Tool: assign_route_to_shipment
```

**What you get back:**
```json
{
  "agentReasoning": "I planned your shipment of 50 laptops (125 kg total) from Chicago Central warehouse to New York 10001.\n\n**Shipment Created:**\n- Tracking Number: SP-A1B2C3D4\n- Status: CARRIER_CONFIRMED\n\n**Route Selected:** Chicago → New York via I-80 Highway\n- Distance: 1,200 km\n- Estimated transit: 18 hours (road freight)\n\n**Carrier Selected:** FedEx Express\n- Why: Cheapest at $387.50 for EXPRESS service, 99.1% on-time delivery, supports fragile handling\n- Competitors: UPS ($412), DHL ($395)\n\n**Estimated Delivery:** September 3, 2026 (within your deadline of September 5)\n\n**Carbon footprint:** 11.5 kg CO₂\n\n**Special handling:** Fragile flag applied — carrier notified.",
  "toolsCalled": [
    "get_warehouse_capacity",
    "optimize_route",
    "get_available_carriers",
    "get_carrier_quote",
    "get_carrier_quote",
    "get_carrier_quote",
    "create_shipment",
    "assign_carrier_to_shipment",
    "assign_route_to_shipment"
  ]
}
```

---

### Example C — Streaming response (see AI think in real time)

Open a terminal and run:

```bash
curl -N "http://localhost:8000/api/v1/stream?q=Find+all+shipments+in+transit+and+tell+me+which+ones+are+late"
```

You will see tokens appear one by one as the AI writes:

```
data: {"type": "tool_call", "data": "list_shipments"}
data: {"type": "tool_result", "data": "done"}
data: {"type": "token", "data": "Based"}
data: {"type": "token", "data": " on"}
data: {"type": "token", "data": " the"}
data: {"type": "token", "data": " current"}
...
data: [DONE]
```

This is useful for building a chat interface where the answer appears word by word.

---

### Example D — Check a specific shipment

```bash
curl http://localhost:8000/api/v1/shipments/SP-A1B2C3D4
```

```json
{
  "id": "abc-123...",
  "trackingNumber": "SP-A1B2C3D4",
  "status": "CARRIER_CONFIRMED",
  "priority": "EXPRESS",
  "originWarehouseId": "wh-001",
  "destinationAddress": {
    "city": "New York",
    "country": "US",
    "postalCode": "10001"
  },
  "totalWeight": 125.0,
  "totalValue": 60000.0,
  "carrierId": "fedex-express",
  "statusHistory": [
    {"status": "DRAFT",             "timestamp": "2026-08-31T10:00:00Z", "notes": "Shipment created"},
    {"status": "CARRIER_CONFIRMED", "timestamp": "2026-08-31T10:00:05Z", "notes": "Carrier FedEx Express assigned"}
  ]
}
```

---

### Example E — Raw GraphQL (for developers)

Sometimes you just want to query the data directly without the AI layer:

```bash
curl -X POST http://localhost:8000/api/v1/graphql \
  -H "Content-Type: application/json" \
  -d '{
    "query": "{ warehouses { id code name availableM3 utilizationPct address { city country } } }"
  }'
```

```json
{
  "data": {
    "warehouses": [
      {
        "id": "wh-001",
        "code": "CHI-01",
        "name": "Chicago Central",
        "availableM3": 50000.0,
        "utilizationPct": 0.0,
        "address": {"city": "Chicago", "country": "US"}
      },
      {
        "id": "wh-002",
        "code": "NYC-01",
        "name": "New York East",
        "availableM3": 35000.0,
        "utilizationPct": 0.0,
        "address": {"city": "New York", "country": "US"}
      }
    ]
  }
}
```

---

### Example F — Update shipment status

The AI can do this, or you can call the MCP tool directly via JSON-RPC:

```bash
# The Apollo MCP Server speaks JSON-RPC 2.0 on POST /mcp
curl -X POST http://localhost:8090/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "UpdateShipmentStatus",
      "arguments": {
        "id": "YOUR-SHIPMENT-ID",
        "status": "IN_TRANSIT",
        "notes": "Package picked up by FedEx driver at 09:30 AM"
      }
    },
    "id": 1
  }'
```

> **Tip:** You rarely need to call MCP directly. The AI agent handles it for you.
> Use `/api/v1/ask` with a plain-English question instead.

**Valid status values and what they mean:**

| Status | Meaning |
|--------|---------|
| `DRAFT` | Shipment record created, not yet confirmed |
| `PENDING_CARRIER` | Looking for a carrier to take it |
| `CARRIER_CONFIRMED` | A carrier said yes |
| `PICKUP_SCHEDULED` | Collection time booked at warehouse |
| `IN_TRANSIT` | Package is on its way |
| `OUT_FOR_DELIVERY` | On the delivery truck |
| `DELIVERED` | Arrived at destination |
| `EXCEPTION` | Something went wrong (damage, delay, etc.) |
| `CANCELLED` | Shipment was cancelled |

---

## 7. Switching the AI Model

You **never need to rebuild** to change models. Just edit `.env` and restart the gateway.

```bash
# Edit .env and change this line:
OPENROUTER_MODEL=openai/gpt-4o

# Restart only the gateway (takes 5 seconds):
docker-compose restart fastapi-gateway
```

### Popular models and when to use them

| Model | Cost | Speed | Best for |
|-------|------|-------|---------|
| `meta-llama/llama-3.1-8b-instruct` | **Free** | Fast | Testing, development |
| `meta-llama/llama-3.1-70b-instruct` | Free tier | Medium | Better reasoning, still free |
| `anthropic/claude-3.5-sonnet` | ~$3/1M tokens | Medium | Complex multi-step planning |
| `openai/gpt-4o` | ~$5/1M tokens | Medium | Well-rounded |
| `google/gemini-pro-1.5` | ~$1.25/1M tokens | Fast | Large context windows |

For this logistics domain, **Claude 3.5 Sonnet** or **Llama 3.1 70B** produce the best reasoning about routes, costs, and trade-offs.

---

## 8. Common Errors and Fixes

### "OPENROUTER_API_KEY not set"
```
KeyError: 'OPENROUTER_API_KEY'
```
**Fix:** Make sure you copied `.env.example` to `.env` and filled in your key.
```bash
cat .env  # Check the file exists and has the key
```

---

### "No routes available for these constraints"
The AI returns: *"No routes available for these constraints"*

**Why:** The route-service database is empty. No routes have been created yet.

**Fix:** Create a test route first:
```bash
curl -X POST http://localhost:8000/api/v1/graphql \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { createRoute(input: { name: \"Chicago to New York Road\", originWarehouseId: \"wh-001\", destinationPostalCode: \"10001\", transportMode: ROAD, totalDistanceKm: 1200, estimatedDurationHours: 18, costPerKg: 0.85, maxWeightKg: 5000, maxVolumeM3: 50 }) { id name } }"
  }'
```

---

### Services won't start — "Connection refused to postgres"
**Why:** PostgreSQL is still starting up.

**Fix:** Check health:
```bash
docker-compose ps       # Is postgres "healthy"?
docker-compose logs postgres  # Any errors?
```
Wait 15 seconds and try again.

---

### Apollo Router: "Subgraph not reachable"
**Why:** The Spring Boot services haven't started yet, or `supergraph.graphql` is outdated.

**Fix:**
```bash
# Check all services are up:
docker-compose ps

# Rebuild the supergraph schema:
cd apollo-federation
rover supergraph compose --config supergraph.yaml > supergraph.graphql
cd ..
docker-compose restart apollo-router
```

---

### Maven build fails: "Source option 17 not supported"
**Why:** You have JDK 11 or older installed.

**Fix:** Install JDK 17 from https://adoptium.net  
Check your version: `java -version`

---

### Port already in use
```
Bind for 0.0.0.0:8081 failed: port is already allocated
```
**Fix:** Stop whatever is using that port, or change the port in `docker-compose.yml`.
```bash
# Find what's using port 8081:
lsof -i :8081          # Mac/Linux
netstat -ano | findstr 8081  # Windows
```

---

## 9. Developer Reference

### Running services locally (without Docker)

Useful when developing — faster restarts, IDE debugger works.

```bash
# 1. Start only the database in Docker
docker-compose up -d postgres

# 2. Run each Spring Boot service from your IDE or terminal
# The "local" profile connects to localhost:5432

cd domain-services/shipment-service
mvn spring-boot:run -Dspring-boot.run.profiles=local

cd domain-services/route-service
mvn spring-boot:run -Dspring-boot.run.profiles=local

cd domain-services/carrier-service
mvn spring-boot:run -Dspring-boot.run.profiles=local

cd domain-services/warehouse-service
mvn spring-boot:run -Dspring-boot.run.profiles=local

# 3. Compose supergraph (points to localhost services)
cd apollo-federation
rover supergraph compose --config supergraph.yaml > supergraph.graphql

# 4. Start Apollo Router in Docker (it talks to localhost services via host networking)
docker-compose up apollo-router

# 5. Start the Apollo MCP Server in Docker (it points to localhost Apollo Router)
#    The official image handles everything — no custom Python server
docker-compose up apollo-mcp-server

cd fastapi-gateway
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

---

### IDE Setup (IntelliJ IDEA)

1. **File → Open** → select the **root `pom.xml`** → Open as Project
2. IntelliJ imports all 4 modules automatically
3. Each service appears in the **Maven** sidebar on the right
4. To run a service: open its `*Application.java` → click the green ▶ button
5. Set VM options: `-Dspring.profiles.active=local`

---

### Database access

Connect with any SQL client (DBeaver, TablePlus, pgAdmin):

| Setting | Value |
|---------|-------|
| Host | `localhost` |
| Port | `5432` |
| Database | `shipment_planner` |
| Username | `sp_admin` |
| Password | `sp_admin_pass` (or whatever you set in `.env`) |

Each service's tables are in their own schema:
```sql
-- See all shipments:
SELECT * FROM shipment.shipments;

-- See all routes:
SELECT * FROM route.routes;

-- See all carriers:
SELECT * FROM carrier.carriers;

-- See all warehouses:
SELECT * FROM warehouse.warehouses;
```

---

### Adding a new MCP tool

With the **official Apollo MCP Server** this is just creating one `.graphql` file — no Python, no restarts.

**Example: add a tool that finds delayed shipments**

1. Create `apollo-mcp-server/operations/ListInTransitShipments.graphql`:

```graphql
# Tool: list_in_transit_shipments
# Returns all shipments currently in transit so we can check for delays.
query ListInTransitShipments($limit: Int = 50) {
  shipments(status: IN_TRANSIT, limit: $limit) {
    id
    trackingNumber
    estimatedDelivery
    destinationAddress {
      city
      country
      postalCode
    }
  }
}
```

2. That's it. The Apollo MCP Server hot-reloads the `operations/` directory.  
   On the **next AI request** the agent discovers `ListInTransitShipments` as a new tool — **no restart, no code change**.

> **Rule of thumb:** One `.graphql` file = one MCP tool.  
> The operation name inside the file becomes the tool name.

---

### All API endpoints at a glance

| Method | URL | What it does |
|--------|-----|-------------|
| `GET` | `/health` | System health check |
| `GET` | `/api/v1/tools` | List all AI tools available |
| `POST` | `/api/v1/ask` | Free-form AI question |
| `GET` | `/api/v1/stream?q=...` | Streaming AI answer (SSE) |
| `POST` | `/api/v1/plan` | Full AI shipment plan |
| `POST` | `/api/v1/graphql` | Raw GraphQL pass-through |
| `GET` | `/api/v1/warehouses` | List warehouses with capacity |
| `GET` | `/api/v1/shipments` | List shipments (filter by status) |
| `GET` | `/api/v1/shipments/{id}` | Get one shipment |
| `GET` | `/api/v1/carriers` | Get carriers for a shipment profile |
| `POST` | `/api/v1/routes/optimize` | Optimize a route |
| `GET` | `/docs` | Interactive Swagger UI |

---

### Shipment priority options

| Priority | Use when | Typical cost multiplier |
|----------|---------|------------------------|
| `STANDARD` | No rush, 5–7 days fine | 1× |
| `EXPRESS` | Need it in 2–3 days | 2× |
| `OVERNIGHT` | Next morning delivery | 4× |
| `SAME_DAY` | Today only | 8× |

---

---

### Apollo MCP Server — how the config works

```
apollo-mcp-server/
├── config.yaml          ← Master config: where operations live, which Router to call
└── operations/          ← Drop .graphql files here; each becomes one MCP tool
    ├── GetShipment.graphql          → tool "GetShipment"
    ├── OptimizeRoute.graphql        → tool "OptimizeRoute"
    └── ...
```

`config.yaml` key settings:
```yaml
operations:
  source: local
  paths:
    - /mcp-operations/         # mounted from ./apollo-mcp-server/operations/

endpoint: http://apollo-router:4000/graphql   # where to send the GraphQL queries

transport:
  type: streamable_http         # JSON-RPC 2.0 over HTTP POST /mcp
  port: 8000
```

The FastAPI gateway's `mcp_client.py` speaks this JSON-RPC protocol:
- `POST /mcp` → `{"jsonrpc":"2.0","method":"tools/list","id":1}` — discover tools
- `POST /mcp` → `{"jsonrpc":"2.0","method":"tools/call","params":{"name":"...","arguments":{...}},"id":2}` — run a tool

---

*Built with LangGraph · Apollo Federation v2 · Official Apollo MCP Server · Spring Boot 3 · FastAPI · PostgreSQL 16*
