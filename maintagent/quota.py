"""Canlı soru sınırı: herkese açık demoda Groq'un günlük hakkı tek kişi tarafından bitirilmesin.

İki sınır var: IP başına saatlik ve toplam günlük. 0 sınırsız demektir (yerelde varsayılan).
Sayaçlar bellekte tutulur; sunucu yeniden başlarsa sıfırlanır. Demo için bu yeterli.
"""

import threading
import time
from collections import deque
from typing import Callable

HOUR, DAY = 3600, 24 * 3600


class LiveQuota:
    def __init__(self, per_ip_per_hour: int = 0, per_day: int = 0, clock: Callable[[], float] = time.time):
        self.per_ip_per_hour, self.per_day, self.clock = per_ip_per_hour, per_day, clock
        self._day: deque[float] = deque()
        self._by_ip: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _trim(q: deque, window: int, now: float) -> None:
        while q and now - q[0] >= window:
            q.popleft()

    def try_take(self, ip: str) -> str | None:
        """Hak varsa bir soru düşer ve None döner; yoksa kullanıcıya gösterilecek mesajı döndürür."""
        with self._lock:
            now = self.clock()
            self._trim(self._day, DAY, now)
            mine = self._by_ip.setdefault(ip, deque())
            self._trim(mine, HOUR, now)
            if self.per_day and len(self._day) >= self.per_day:
                return "Bugünkü canlı soru hakkı doldu. Kayıtlı örnek çalıştırmaları izleyebilirsin."
            if self.per_ip_per_hour and len(mine) >= self.per_ip_per_hour:
                return "Bu saat için canlı soru hakkın doldu. Kayıtlı örnek çalıştırmaları izleyebilirsin."
            self._day.append(now)
            mine.append(now)
            return None

    def remaining_today(self) -> int | None:
        if not self.per_day:
            return None
        with self._lock:
            self._trim(self._day, DAY, self.clock())
            return max(self.per_day - len(self._day), 0)
