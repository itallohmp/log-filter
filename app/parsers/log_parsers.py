import re
from datetime import datetime, time
from typing import Optional, Dict

pattern = re.compile(
    r"\*(\w+\s+\d+\s+\d+:\d+:\d+\.\d+).*?"
    r"Created Translation\s+"
    r"(UDP|TCP)\s+"
    r"(\d+\.\d+\.\d+\.\d+:\d+)\s+"
    r"(\d+\.\d+\.\d+\.\d+:\d+)\s+"
    r"(\d+\.\d+\.\d+\.\d+:\d+)\s+"
    r"(\d+\.\d+\.\d+\.\d+:\d+)\s+"
    r"\d+"
)

def parse_log_line(line: str) -> Optional[Dict]:
    match = pattern.search(line)
    if not match:
        return None

    data, protocolo, origem, nat, destino, destino_final = match.groups()

    return {
        "data": data,
        "protocolo": protocolo,
        "origem": origem,
        "nat": nat,
        "destino": destino,
        "destino_final": destino_final
    }

def parse_time_str(h: Optional[str]) -> Optional[time]:
    if not h:
        return None

    for fmt in ("%H:%M", "%H:%M:%S", "%H:%M:%S.%f"):
        try:
            return datetime.strptime(h, fmt).time()
        except ValueError:
            continue

    return None