from fastapi import APIRouter, HTTPException
import random
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

router = APIRouter()

# ---------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------

class MachineTelemetry(BaseModel):
    machine_id: str
    name: Optional[str] = "DMG Mori DMU 65 monoBLOCK"
    type: Optional[str] = "5-Axis CNC Milling"
    timestamp: str
    temperature_celsius: float
    vibration_mm_s: float
    rpm: int
    spindle_load_pct: float = 68.5
    axis_load: Dict[str, float] = {"X": 42.0, "Y": 56.0, "Z": 61.0, "A": 33.0, "C": 28.0}
    coolant_pressure_bar: float = 65.0
    tool_wear_pct: float = 24.5
    tool_life_hours_remaining: float = 86.4
    health_index: float = 94.5
    status: str
    current_job: Optional[Dict[str, Any]] = None
    predictive_maintenance: Optional[Dict[str, Any]] = None

class MachineSummary(BaseModel):
    id: str
    name: str
    type: str
    bay_location: str
    status: str
    oee: float
    availability_pct: float
    performance_pct: float
    quality_pct: float
    temperature_celsius: float
    vibration_mm_s: float
    rpm: int
    tool_wear_pct: float
    health_index: float
    current_job_po: str
    current_job_part: str
    hours_until_service: float

class FleetOverview(BaseModel):
    plant_name: str
    overall_oee: float
    active_machines_count: int
    total_machines_count: int
    fleet_health_score: float
    machines: List[MachineSummary]

class PredictiveAlert(BaseModel):
    id: str
    machine_id: str
    machine_name: str
    severity: str  # INFO, WARNING, CRITICAL
    category: str  # BEARING, SPINDLE, TOOLING, COOLANT, CALIBRATION
    title: str
    description: str
    recommended_action: str
    detected_at: str
    estimated_time_to_failure: str
    acknowledged: bool = False

class MaintenanceWorkOrderPayload(BaseModel):
    machine_id: str
    task_type: str
    priority: Optional[str] = "HIGH"
    technician: Optional[str] = "Lead Metrology Engineer"
    scheduled_downtime_hours: Optional[float] = 2.0
    notes: Optional[str] = None

class ShipmentTelemetry(BaseModel):
    shipment_id: str
    timestamp: str
    latitude: float
    longitude: float
    temperature_celsius: float
    humidity_percent: float
    shock_event_detected: bool
    # Extended fields for Feature 8
    asn_id: Optional[str] = None
    po_id: Optional[str] = None
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    origin_city: Optional[str] = None
    destination_city: Optional[str] = None
    progress_pct: Optional[float] = None
    eta_hours: Optional[float] = None
    container_id: Optional[str] = None
    seal_intact: Optional[bool] = None
    battery_pct: Optional[float] = None
    status: Optional[str] = None
    altitude_m: Optional[float] = None
    speed_kmh: Optional[float] = None
    g_force_peak: Optional[float] = None
    co2_ppm: Optional[float] = None
    pressure_hpa: Optional[float] = None
    temp_min_threshold: Optional[float] = None
    temp_max_threshold: Optional[float] = None
    humidity_max_threshold: Optional[float] = None


class ShipmentSummary(BaseModel):
    shipment_id: str
    asn_id: str
    po_id: str
    carrier: str
    tracking_number: str
    origin_city: str
    destination_city: str
    status: str
    progress_pct: float
    eta_hours: float
    latitude: float
    longitude: float
    temperature_celsius: float
    humidity_percent: float
    shock_events_count: int
    temp_alert: bool
    humidity_alert: bool
    seal_intact: bool


class ShipmentSensorPoint(BaseModel):
    timestamp: str
    temperature_celsius: float
    humidity_percent: float
    g_force: float
    co2_ppm: float
    pressure_hpa: float
    latitude: float
    longitude: float


class ShockEvent(BaseModel):
    event_id: str
    shipment_id: str
    timestamp: str
    g_force: float
    duration_ms: int
    axis: str
    latitude: float
    longitude: float
    location_desc: str
    severity: str  # LOW, MEDIUM, HIGH
    acknowledged: bool

# ---------------------------------------------------------
# Static Fleet Definitions
# ---------------------------------------------------------

MACHINES_CATALOG = {
    "MAC-DMG-65": {
        "id": "MAC-DMG-65",
        "name": "DMG Mori DMU 65 monoBLOCK 5-Axis",
        "type": "5-Axis CNC Milling Center",
        "bay_location": "Depot Bay Alpha-1",
        "base_temp": 64.0,
        "base_vib": 2.2,
        "base_rpm": 12500,
        "base_coolant": 70.0,
        "base_tool_wear": 22.0,
        "current_po": "PO-2025-00123",
        "current_part": "FG-ACT-SHF-01 (Avionics Enclosure)"
    },
    "MAC-MZK-200": {
        "id": "MAC-MZK-200",
        "name": "Mazak Integrex i-200 Multi-Tasking",
        "type": "Precision Mill-Turn Center",
        "bay_location": "Depot Bay Alpha-2",
        "base_temp": 58.5,
        "base_vib": 1.8,
        "base_rpm": 4500,
        "base_coolant": 45.0,
        "base_tool_wear": 41.0,
        "current_po": "PO-2025-00089",
        "current_part": "FG-FLG-ASMY-88 (Hydraulic Flange)"
    },
    "MAC-ZSS-PRISMO": {
        "id": "MAC-ZSS-PRISMO",
        "name": "Zeiss PRISMO Coordinate Measuring Machine",
        "type": "CMM Metrology & Optical Inspection",
        "bay_location": "Climate Lab Cleanroom Beta",
        "base_temp": 20.1,  # Ultra-tight metrology cleanroom tolerance
        "base_vib": 0.08,
        "base_rpm": 0,
        "base_coolant": 0.0,
        "base_tool_wear": 8.0,
        "current_po": "PO-2025-00123",
        "current_part": "AS9100D Metrology GD&T Verification"
    },
    "MAC-EDM-350": {
        "id": "MAC-EDM-350",
        "name": "AgieCharmilles CUT P 350 Precision Wire EDM",
        "type": "Sub-Micron Wire EDM Cutter",
        "bay_location": "Precision EDM Cell Gamma",
        "base_temp": 24.5,
        "base_vib": 0.45,
        "base_rpm": 0,
        "base_coolant": 18.0,
        "base_tool_wear": 15.0,
        "current_po": "PO-2025-00045",
        "current_part": "PIN-SFT-TI64 (Spline Shaft Teeth)"
    }
}

# Maintain active work orders in-memory
work_orders = []

# ---------------------------------------------------------
# Shipment Transit IoT Catalog — Feature 8
# ---------------------------------------------------------

SHIPMENTS_CATALOG = {
    "SHP-2025-0412": {
        "shipment_id": "SHP-2025-0412",
        "asn_id": "ASN-20251015-7842",
        "po_id": "PO-2025-00123",
        "carrier": "FedEx Aerospace Freight",
        "tracking_number": "FX-889120412-US",
        "container_id": "CONT-AX4-7712",
        "origin_city": "Seattle, WA",
        "destination_city": "Dallas, TX",
        "origin_lat": 47.6062, "origin_lon": -122.3321,
        "dest_lat": 32.7767, "dest_lon": -96.7970,
        "temp_min_threshold": 15.0,
        "temp_max_threshold": 30.0,
        "humidity_max_threshold": 60.0,
        "base_temp": 21.5,
        "base_humidity": 42.0,
        "base_co2": 420.0,
        "duration_hours": 48,
        "elapsed_hours_offset": 12,
        "shock_events": [
            {"event_id": "SHK-001", "g_force": 4.2, "duration_ms": 180, "axis": "Z", "lat": 46.5, "lon": -118.7, "location_desc": "I-90 Freight Hub, Ellensburg WA", "severity": "MEDIUM", "acknowledged": False},
        ]
    },
    "SHP-2025-0389": {
        "shipment_id": "SHP-2025-0389",
        "asn_id": "ASN-20251012-6201",
        "po_id": "PO-2025-00089",
        "carrier": "DHL Global Forwarding",
        "tracking_number": "DHL-88012039-EU",
        "container_id": "CONT-EU3-5521",
        "origin_city": "Mumbai, India",
        "destination_city": "Frankfurt, Germany",
        "origin_lat": 19.0760, "origin_lon": 72.8777,
        "dest_lat": 50.1109, "dest_lon": 8.6821,
        "temp_min_threshold": 10.0,
        "temp_max_threshold": 28.0,
        "humidity_max_threshold": 65.0,
        "base_temp": 24.0,
        "base_humidity": 58.0,
        "base_co2": 450.0,
        "duration_hours": 72,
        "elapsed_hours_offset": 38,
        "shock_events": [
            {"event_id": "SHK-002", "g_force": 2.8, "duration_ms": 95, "axis": "X", "lat": 25.0, "lon": 55.2, "location_desc": "Dubai International Air Freight Terminal", "severity": "LOW", "acknowledged": True},
            {"event_id": "SHK-003", "g_force": 6.1, "duration_ms": 310, "axis": "Y", "lat": 32.1, "lon": 34.8, "location_desc": "Tel Aviv Transfer Hub", "severity": "HIGH", "acknowledged": False},
        ]
    },
    "SHP-2025-0401": {
        "shipment_id": "SHP-2025-0401",
        "asn_id": "ASN-20251013-6875",
        "po_id": "PO-2025-00045",
        "carrier": "FedEx International Priority",
        "tracking_number": "FX-990043712-AP",
        "container_id": "CONT-AP1-9903",
        "origin_city": "Shenzhen, China",
        "destination_city": "Los Angeles, CA",
        "origin_lat": 22.5431, "origin_lon": 114.0579,
        "dest_lat": 34.0522, "dest_lon": -118.2437,
        "temp_min_threshold": 18.0,
        "temp_max_threshold": 35.0,
        "humidity_max_threshold": 70.0,
        "base_temp": 29.5,
        "base_humidity": 66.5,
        "base_co2": 490.0,
        "duration_hours": 96,
        "elapsed_hours_offset": 72,
        "shock_events": []
    }
}



@router.get("/fleet", response_model=FleetOverview)
async def get_fleet_overview():
    """
    Returns real-time SCADA digital twin telemetry across the complete shop floor machinery fleet.
    """
    machines_summary = []
    
    for m_id, m in MACHINES_CATALOG.items():
        # Physics-based dynamic noise
        temp_delta = random.uniform(-1.5, 2.5)
        vib_delta = random.uniform(-0.15, 0.25)
        temp = round(m["base_temp"] + temp_delta, 1)
        vib = round(max(0.01, m["base_vib"] + vib_delta), 2)
        
        status = "OPTIMAL"
        if m_id == "MAC-DMG-65" and temp > 74.0:
            status = "WARNING"
        elif m_id == "MAC-ZSS-PRISMO" and (temp > 21.0 or temp < 19.5):
            status = "WARNING"

        # Calculate high-precision OEE components
        avail = round(random.uniform(94.0, 98.5), 1)
        perf = round(random.uniform(91.0, 96.0), 1)
        qual = round(random.uniform(98.8, 99.8), 1)
        oee = round((avail * perf * qual) / 10000.0, 1)
        
        health = round(100.0 - (m["base_tool_wear"] * 0.25) - (vib * 2.5), 1)
        hours_to_service = round(max(12.0, 240.0 - (m["base_tool_wear"] * 3.2)), 1)
        
        machines_summary.append(MachineSummary(
            id=m["id"],
            name=m["name"],
            type=m["type"],
            bay_location=m["bay_location"],
            status=status,
            oee=oee,
            availability_pct=avail,
            performance_pct=perf,
            quality_pct=qual,
            temperature_celsius=temp,
            vibration_mm_s=vib,
            rpm=m["base_rpm"] + (random.randint(-20, 40) if m["base_rpm"] > 0 else 0),
            tool_wear_pct=m["base_tool_wear"],
            health_index=health,
            current_job_po=m["current_po"],
            current_job_part=m["current_part"],
            hours_until_service=hours_to_service
        ))

    avg_oee = round(sum(m.oee for m in machines_summary) / len(machines_summary), 1)
    avg_health = round(sum(m.health_index for m in machines_summary) / len(machines_summary), 1)

    return FleetOverview(
        plant_name="Apex Precision Aerospace Facility (Plant #1)",
        overall_oee=avg_oee,
        active_machines_count=len(machines_summary),
        total_machines_count=len(machines_summary),
        fleet_health_score=avg_health,
        machines=machines_summary
    )


@router.get("/machine/{machine_id}", response_model=MachineTelemetry)
async def get_live_machine_telemetry(machine_id: str):
    """
    Returns real-time IoT multi-channel telemetry and predictive diagnostics for a specific machine.
    """
    # Fallback to DMG Mori if ID not found or legacy mock ID
    m_info = MACHINES_CATALOG.get(machine_id, MACHINES_CATALOG.get("MAC-DMG-65"))
    if machine_id == "MAC-8842-CNC":
        m_info = MACHINES_CATALOG["MAC-DMG-65"]

    base_temp = m_info["base_temp"]
    base_vib = m_info["base_vib"]
    base_rpm = m_info["base_rpm"]

    temp = round(base_temp + random.uniform(-2.0, 4.0), 1)
    vib = round(max(0.01, base_vib + random.uniform(-0.2, 0.4)), 2)
    rpm = base_rpm + (random.randint(-40, 60) if base_rpm > 0 else 0)

    status = "OPTIMAL"
    if temp > 72.0 or vib > 3.8:
        status = "WARNING"
    if temp > 78.0 or vib > 5.5:
        status = "CRITICAL"

    axis_loads = {
        "X": round(random.uniform(35.0, 65.0), 1),
        "Y": round(random.uniform(40.0, 72.0), 1),
        "Z": round(random.uniform(50.0, 80.0), 1),
        "A": round(random.uniform(20.0, 45.0), 1),
        "C": round(random.uniform(15.0, 38.0), 1)
    }

    tool_wear = round(m_info["base_tool_wear"] + random.uniform(0.1, 0.8), 1)
    tool_life_remaining = round(max(5.0, 120.0 - (tool_wear * 1.5)), 1)
    health = round(max(60.0, 100.0 - (tool_wear * 0.3) - (vib * 2.8)), 1)

    return MachineTelemetry(
        machine_id=machine_id,
        name=m_info["name"],
        type=m_info["type"],
        timestamp=datetime.utcnow().isoformat() + "Z",
        temperature_celsius=temp,
        vibration_mm_s=vib,
        rpm=rpm,
        spindle_load_pct=round(random.uniform(55.0, 78.0), 1),
        axis_load=axis_loads,
        coolant_pressure_bar=round(m_info["base_coolant"] + random.uniform(-2.0, 2.0), 1),
        tool_wear_pct=tool_wear,
        tool_life_hours_remaining=tool_life_remaining,
        health_index=health,
        status=status,
        current_job={
            "po_id": m_info["current_po"],
            "part_name": m_info["current_part"],
            "target_qty": 50,
            "completed_qty": 38,
            "cycle_time_seconds": 240,
            "spindle_runtime_hours": 1420.5
        },
        predictive_maintenance={
            "bearing_health_score": round(max(70.0, 98.0 - (vib * 4.0)), 1),
            "thermal_stability": "STABLE" if temp < 70.0 else "ELEVATED",
            "lubrication_level_pct": 87.0,
            "recommended_action": "Routine Spindle Bearing Lubrication Scheduled" if vib < 3.0 else "Inspect Ceramic Hybrid Spindle Bearings",
            "days_until_service": round(tool_life_remaining / 8.0, 1)
        }
    )


@router.get("/predictive-maintenance/alerts", response_model=List[PredictiveAlert])
async def get_predictive_alerts():
    """
    Returns AI-generated predictive maintenance anomaly warnings across all shop floor machines.
    """
    alerts = [
        PredictiveAlert(
            id="ALT-2025-091",
            machine_id="MAC-DMG-65",
            machine_name="DMG Mori DMU 65 monoBLOCK 5-Axis",
            severity="WARNING",
            category="BEARING",
            title="Spindle Ceramic Bearing Micro-Harmonic Vibration",
            description="High-frequency accelerometer sensor detected 3.4 mm/s RMS peak on Z-axis housing during 12,000 RPM pass.",
            recommended_action="Execute automated grease purge cycle and inspect spindle cartridge pre-load within 36 operating hours.",
            detected_at=(datetime.utcnow() - timedelta(minutes=42)).isoformat() + "Z",
            estimated_time_to_failure="140 operating hours",
            acknowledged=False
        ),
        PredictiveAlert(
            id="ALT-2025-088",
            machine_id="MAC-MZK-200",
            machine_name="Mazak Integrex i-200 Mill-Turn",
            severity="INFO",
            category="TOOLING",
            title="Carbide Insert Flank Wear Approaching Threshold (41%)",
            description="Tool T04 (Sandvik CoroTurn 300) completed 185 cycles on Inconel 718 hydraulic flange roughing.",
            recommended_action="Index carbide insert edge during next batch setup to prevent thermal work hardening.",
            detected_at=(datetime.utcnow() - timedelta(hours=2, minutes=15)).isoformat() + "Z",
            estimated_time_to_failure="48 operating hours",
            acknowledged=True
        ),
        PredictiveAlert(
            id="ALT-2025-084",
            machine_id="MAC-ZSS-PRISMO",
            machine_name="Zeiss PRISMO CMM",
            severity="INFO",
            category="CALIBRATION",
            title="Sub-Micron Optical Stylus Qualification Due",
            description="VAST Gold probe sensor logged 500 probing inspection cycles since last ruby sphere calibration.",
            recommended_action="Run automated 25-point master sphere qualification routine before inspecting next aerospace batch.",
            detected_at=(datetime.utcnow() - timedelta(hours=5)).isoformat() + "Z",
            estimated_time_to_failure="72 operating hours",
            acknowledged=False
        )
    ]
    return alerts


@router.post("/maintenance/work-order")
async def schedule_maintenance_work_order(payload: MaintenanceWorkOrderPayload):
    """
    Dispatches a predictive maintenance work order to shop floor maintenance engineering.
    """
    wo_id = f"WO-{datetime.now().strftime('%Y%m%d')}-{random.randint(100, 999)}"
    machine_name = MACHINES_CATALOG.get(payload.machine_id, {}).get("name", payload.machine_id)
    
    record = {
        "work_order_id": wo_id,
        "machine_id": payload.machine_id,
        "machine_name": machine_name,
        "task_type": payload.task_type,
        "priority": payload.priority,
        "technician": payload.technician,
        "scheduled_downtime_hours": payload.scheduled_downtime_hours,
        "notes": payload.notes or f"Automated maintenance dispatched from Predictive Telemetry Twin.",
        "status": "SCHEDULED",
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    work_orders.append(record)
    
    return {
        "status": "success",
        "message": f"Predictive Maintenance Work Order {wo_id} successfully created and dispatched to {payload.technician}.",
        "work_order": record
    }


@router.get("/shipment/{shipment_id}", response_model=ShipmentTelemetry)
async def get_live_shipment_telemetry(shipment_id: str):
    """
    Returns comprehensive real-time IoT sensor data from a specific in-transit shipping container.
    """
    s = SHIPMENTS_CATALOG.get(shipment_id)
    if not s:
        # Legacy fallback
        s = SHIPMENTS_CATALOG["SHP-2025-0412"]

    # Time-based progress simulation (cycles every hour for demo)
    current_time = time.time()
    elapsed_cycle = (current_time % 3600) / 3600.0
    # Incorporate catalog offset to give each shipment different in-progress state
    total_progress = min(0.99, (s["elapsed_hours_offset"] / s["duration_hours"]) + elapsed_cycle * 0.05)

    current_lat = round(s["origin_lat"] + (s["dest_lat"] - s["origin_lat"]) * total_progress, 4)
    current_lon = round(s["origin_lon"] + (s["dest_lon"] - s["origin_lon"]) * total_progress, 4)

    temp = round(s["base_temp"] + random.uniform(-1.2, 1.8), 2)
    humidity = round(s["base_humidity"] + random.uniform(-3.0, 4.0), 2)
    g_force_peak = round(random.uniform(0.8, 2.1), 2)
    shock_detected = random.random() > 0.96

    battery = round(max(15.0, 92.0 - (total_progress * 35.0)), 1)
    eta_hours = round(s["duration_hours"] * (1.0 - total_progress), 1)

    return ShipmentTelemetry(
        shipment_id=s["shipment_id"],
        asn_id=s["asn_id"],
        po_id=s["po_id"],
        carrier=s["carrier"],
        tracking_number=s["tracking_number"],
        container_id=s["container_id"],
        origin_city=s["origin_city"],
        destination_city=s["destination_city"],
        timestamp=datetime.utcnow().isoformat() + "Z",
        latitude=current_lat,
        longitude=current_lon,
        temperature_celsius=temp,
        humidity_percent=humidity,
        shock_event_detected=shock_detected,
        progress_pct=round(total_progress * 100, 1),
        eta_hours=eta_hours,
        seal_intact=True,
        battery_pct=battery,
        status="IN_TRANSIT",
        altitude_m=round(random.uniform(9200.0, 10800.0), 0) if s.get("base_co2", 0) > 440 else round(random.uniform(0.0, 500.0), 0),
        speed_kmh=round(random.uniform(820.0, 920.0), 1) if s.get("base_co2", 0) > 440 else round(random.uniform(55.0, 95.0), 1),
        g_force_peak=g_force_peak,
        co2_ppm=round(s["base_co2"] + random.uniform(-10.0, 20.0), 1),
        pressure_hpa=round(1013.0 + random.uniform(-8.0, 5.0), 1),
        temp_min_threshold=s["temp_min_threshold"],
        temp_max_threshold=s["temp_max_threshold"],
        humidity_max_threshold=s["humidity_max_threshold"]
    )


@router.get("/shipments", response_model=List[ShipmentSummary])
async def get_all_active_shipments():
    """
    Returns a fleet overview of all active in-transit shipments with current GPS positions and sensor status.
    """
    result = []
    current_time = time.time()

    for sid, s in SHIPMENTS_CATALOG.items():
        elapsed_cycle = (current_time % 3600) / 3600.0
        total_progress = min(0.99, (s["elapsed_hours_offset"] / s["duration_hours"]) + elapsed_cycle * 0.05)

        current_lat = round(s["origin_lat"] + (s["dest_lat"] - s["origin_lat"]) * total_progress, 4)
        current_lon = round(s["origin_lon"] + (s["dest_lon"] - s["origin_lon"]) * total_progress, 4)
        temp = round(s["base_temp"] + random.uniform(-1.2, 1.8), 2)
        humidity = round(s["base_humidity"] + random.uniform(-3.0, 4.0), 2)

        temp_alert = temp > s["temp_max_threshold"] or temp < s["temp_min_threshold"]
        humidity_alert = humidity > s["humidity_max_threshold"]

        result.append(ShipmentSummary(
            shipment_id=s["shipment_id"],
            asn_id=s["asn_id"],
            po_id=s["po_id"],
            carrier=s["carrier"],
            tracking_number=s["tracking_number"],
            origin_city=s["origin_city"],
            destination_city=s["destination_city"],
            status="IN_TRANSIT",
            progress_pct=round(total_progress * 100, 1),
            eta_hours=round(s["duration_hours"] * (1.0 - total_progress), 1),
            latitude=current_lat,
            longitude=current_lon,
            temperature_celsius=temp,
            humidity_percent=humidity,
            shock_events_count=len(s["shock_events"]),
            temp_alert=temp_alert,
            humidity_alert=humidity_alert,
            seal_intact=True
        ))

    return result


@router.get("/shipment/{shipment_id}/sensors", response_model=List[ShipmentSensorPoint])
async def get_shipment_sensor_history(shipment_id: str, points: int = 24):
    """
    Returns a historical timeline of IoT sensor readings (temperature, humidity, g-force, CO2, pressure, GPS) for a shipment.
    """
    s = SHIPMENTS_CATALOG.get(shipment_id, SHIPMENTS_CATALOG["SHP-2025-0412"])
    history = []
    now = datetime.utcnow()

    for i in range(points):
        # Go back in time
        t = now - timedelta(hours=(points - i))
        fraction = i / max(1, (points - 1))
        lat = round(s["origin_lat"] + (s["dest_lat"] - s["origin_lat"]) * fraction, 4)
        lon = round(s["origin_lon"] + (s["dest_lon"] - s["origin_lon"]) * fraction, 4)
        temp_drift = random.uniform(-1.5, 2.0)
        humidity_drift = random.uniform(-4.0, 5.0)
        history.append(ShipmentSensorPoint(
            timestamp=t.isoformat() + "Z",
            temperature_celsius=round(s["base_temp"] + temp_drift, 2),
            humidity_percent=round(s["base_humidity"] + humidity_drift, 2),
            g_force=round(random.uniform(0.7, 2.5), 2),
            co2_ppm=round(s["base_co2"] + random.uniform(-15, 30), 1),
            pressure_hpa=round(1013.0 + random.uniform(-10.0, 8.0), 1),
            latitude=lat,
            longitude=lon
        ))

    return history


@router.get("/shipment/{shipment_id}/shocks", response_model=List[ShockEvent])
async def get_shipment_shock_events(shipment_id: str):
    """
    Returns the full shock/impact event log for an in-transit shipment container.
    """
    s = SHIPMENTS_CATALOG.get(shipment_id, SHIPMENTS_CATALOG["SHP-2025-0412"])
    events = []
    now = datetime.utcnow()
    for idx, ev in enumerate(s["shock_events"]):
        events.append(ShockEvent(
            event_id=ev["event_id"],
            shipment_id=shipment_id,
            timestamp=(now - timedelta(hours=(len(s["shock_events"]) - idx) * 4)).isoformat() + "Z",
            g_force=ev["g_force"],
            duration_ms=ev["duration_ms"],
            axis=ev["axis"],
            latitude=ev["lat"],
            longitude=ev["lon"],
            location_desc=ev["location_desc"],
            severity=ev["severity"],
            acknowledged=ev["acknowledged"]
        ))
    return events


@router.get("/shipments/alerts")
async def get_shipment_condition_alerts():
    """
    Returns active cold-chain and condition monitoring alerts across all in-transit shipments.
    """
    alerts = []
    current_time = time.time()

    for sid, s in SHIPMENTS_CATALOG.items():
        elapsed_cycle = (current_time % 3600) / 3600.0
        total_progress = min(0.99, (s["elapsed_hours_offset"] / s["duration_hours"]) + elapsed_cycle * 0.05)
        temp = round(s["base_temp"] + random.uniform(-1.2, 1.8), 2)
        humidity = round(s["base_humidity"] + random.uniform(-3.0, 4.0), 2)

        for ev in s["shock_events"]:
            if not ev["acknowledged"]:
                alerts.append({
                    "alert_id": f"ALT-{ev['event_id']}",
                    "shipment_id": sid,
                    "asn_id": s["asn_id"],
                    "po_id": s["po_id"],
                    "type": "SHOCK_EVENT",
                    "severity": ev["severity"],
                    "title": f"Impact Event Detected — {ev['g_force']}G on {ev['axis']}-Axis",
                    "description": f"Shock sensor recorded {ev['g_force']}G peak over {ev['duration_ms']}ms at {ev['location_desc']}.",
                    "recommended_action": "Inspect packaging integrity and re-certify aerospace parts via CMM inspection upon delivery.",
                    "detected_at": (datetime.utcnow() - timedelta(hours=3)).isoformat() + "Z",
                    "acknowledged": False
                })

        if temp > s["temp_max_threshold"]:
            alerts.append({
                "alert_id": f"ALT-TEMP-{sid}",
                "shipment_id": sid,
                "asn_id": s["asn_id"],
                "po_id": s["po_id"],
                "type": "TEMP_EXCURSION",
                "severity": "WARNING",
                "title": f"Temperature Excursion — {temp}°C (Limit: {s['temp_max_threshold']}°C)",
                "description": f"Container temperature exceeded cold-chain threshold. Current: {temp}°C, Max allowed: {s['temp_max_threshold']}°C.",
                "recommended_action": "Contact carrier to verify active cooling status. Document excursion for AS9100D nonconformance report.",
                "detected_at": datetime.utcnow().isoformat() + "Z",
                "acknowledged": False
            })

    return {"alerts": alerts, "total_count": len(alerts)}

