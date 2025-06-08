# wallbox/base.py
from abc import ABC, abstractmethod

class WallboxBase(ABC):
    @abstractmethod
    def readData(self):
        """
        Reads current state and returns a dict with keys like:
        - charging_power
        - temperature
        - voltage_phases
        - is_connected
        - is_charging
        - charging_current
        """
        pass

    @abstractmethod
    def setCharging(self, current: int, start_charging: bool) -> int:
        """
        Sets the charging current and start/stop charging.
        Returns:
            HTTP status code or error code (-1 if failed)
        """
        pass

    @abstractmethod
    def isAvailable(self) -> bool:
        """
        Check if the wallbox is available (online and reachable).
        """
        pass

    @abstractmethod
    def isCharging(self) -> bool:
        """
        Returns the true if wallbox is charging.
        """
        pass

    @abstractmethod
    def getCharingLevel(self) -> int:
        """
        Returns the actual charging level.
        """
        pass

    @abstractmethod
    def getRetryCount(self) -> int:
        """
        Returns the retry count.
        """
        pass

    @abstractmethod
    def setRetryCount(self, retrycount: int): 
        """
        Sets the retry count
        """
        pass

    @abstractmethod
    def isActiveCharingSession(self) -> bool: 
        """
        Returns true if there is a active charging session.
        """
        pass

    @abstractmethod
    def setActiveCharingSession(self, status: bool): 
        """
        Sets the status of charging session. True = active
        """
        pass

    @abstractmethod
    def getID(self) -> int:
        """
        Returns the wallbox id.
        """
        pass