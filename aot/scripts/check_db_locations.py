"""Print lat/lng coordinates stored in Site, Zone, and Device tables."""
from aot.start_flask_ui import app
from aot.databases.models import Site, Zone, Device

with app.app_context():
    sites = Site.query.filter(Site.latitude != None).all()
    for s in sites:
        print(f"Site {s.name}: {s.latitude}, {s.longitude}")
        
    zones = Zone.query.filter(Zone.latitude != None).all()
    for z in zones:
        print(f"Zone {z.name}: {z.latitude}, {z.longitude}")
        
    devices = Device.query.filter(Device.latitude != None).all()
    for d in devices:
        print(f"Device {d.name}: {d.latitude}, {d.longitude}")
