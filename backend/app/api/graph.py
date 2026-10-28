from fastapi import APIRouter

router = APIRouter()

@router.get("/query")
def query_capability_graph(process: str, material: str):
    # Mocking a graph traversal that finds all suppliers with a machine
    # capable of the requested process and material.
    
    # In a real graph database/complex SQL, this would traverse:
    # Supplier -> Plant -> Machine -> MachineCapability -> (Process & Material)
    
    return {
        "query": {"process": process, "material": material},
        "graph_results": [
            {
                "supplier_id": "SUP-001",
                "supplier_name": "ABC Components Pvt Ltd",
                "matching_plants": [
                    {
                        "plant_id": "PL-001",
                        "location": "Chennai, India",
                        "matching_machines": [
                            {
                                "machine_id": "MCH-001",
                                "name": "MAZAK Integrex",
                                "capacity_units": 60000,
                                "tolerance_mm": 0.05
                            }
                        ]
                    }
                ]
            },
            {
                "supplier_id": "SUP-002",
                "supplier_name": "XYZ Manufacturing",
                "matching_plants": [
                    {
                        "plant_id": "PL-002",
                        "location": "Pune, India",
                        "matching_machines": [
                            {
                                "machine_id": "MCH-004",
                                "name": "Buhler Carat 105",
                                "capacity_units": 45000,
                                "tolerance_mm": 0.08
                            }
                        ]
                    }
                ]
            }
        ]
    }
