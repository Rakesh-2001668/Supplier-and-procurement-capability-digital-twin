from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.iot_stream import iot_simulator
import asyncio

router = APIRouter()

@router.on_event("startup")
async def startup_event():
    # Start the simulator loop in the background
    asyncio.create_task(iot_simulator.run())

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await iot_simulator.add_client(websocket)
    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        iot_simulator.remove_client(websocket)
