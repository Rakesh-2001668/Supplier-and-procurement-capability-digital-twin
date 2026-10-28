import asyncio
import random
import json
from datetime import datetime

class IoTStreamSimulator:
    def __init__(self):
        self.clients = set()
        self.running = False
        
        self.suppliers = [
            {"id": "SUP-123", "name": "Precision AutoComp", "location": "Chennai", "machine": "5-Axis CNC"},
            {"id": "SUP-442", "name": "Kovai Diecast", "location": "Coimbatore", "machine": "HPDC 1200T"},
            {"id": "SUP-891", "name": "Salem Light Alloys", "location": "Salem", "machine": "VMC-400"}
        ]
        
    async def add_client(self, websocket):
        self.clients.add(websocket)
        
    def remove_client(self, websocket):
        if websocket in self.clients:
            self.clients.remove(websocket)
            
    async def broadcast(self, message: dict):
        dead_clients = set()
        for client in self.clients:
            try:
                await client.send_text(json.dumps(message))
            except Exception:
                dead_clients.add(client)
        for client in dead_clients:
            self.remove_client(client)
            
    async def run(self):
        self.running = True
        counter = 0
        while self.running:
            await asyncio.sleep(2)
            counter += 1
            
            # Normal Telemetry
            supplier = random.choice(self.suppliers)
            oee = random.randint(88, 98)
            temp = random.randint(55, 75)
            
            msg = {
                "type": "telemetry",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "supplier": supplier["name"],
                "machine": supplier["machine"],
                "oee": oee,
                "temp": temp,
                "status": "Healthy"
            }
            
            # Inject a fault every ~10 ticks
            if counter % 10 == 0:
                msg["type"] = "fault"
                msg["supplier"] = "Precision AutoComp"
                msg["machine"] = "5-Axis CNC"
                msg["oee"] = 24
                msg["temp"] = 142
                msg["status"] = "SPINDLE_OVERHEAT_CRITICAL"
                msg["impact"] = "Capacity drop: -30% (Live)"
            
            await self.broadcast(msg)

iot_simulator = IoTStreamSimulator()
