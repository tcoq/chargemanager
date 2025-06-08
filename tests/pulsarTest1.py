import sys
import os

# Lösung von Pfadproblemen
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from wallbox import pulsarwallboxcontroller
import pprint
pc = pulsarwallboxcontroller.PulsarWallboxController()
data = pc.readData()
print(data)
print(pc.isAvailable())