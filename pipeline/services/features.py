"""Canonical feature flags derived from the equipment lists the spec sources print.

Each source words things differently ("Heat pump", "Heat Pump", "V2L (Vehicle to
Load) - Inside", "Vehicle-to-Load (V2L) Capability"). A flag is set when any
listed item matches its pattern, so the app can filter by the same handful of
features whichever page they came from. The raw list is kept alongside.
"""
from __future__ import annotations

import re

# flag -> (label, pattern over the lower-cased item text)
FLAGS: dict[str, tuple[str, str]] = {
    "heat_pump": ("Heat pump", r"\bheat pump\b"),
    # Kia lists the cabin socket as plain "Vehicle-to-Load (V2L) Capability" and the
    # exterior one as "... with Adapter"; Carwow says "- Inside" / "- Outside".
    "v2l_internal": ("Internal V2L socket", r"(v2l|vehicle.to.load)(?!.*(outside|exterior|outdoor|external|adapt[eo]r|charge port)).*(inside|interior|internal|indoor|cabin|in-car|socket|plug|capability$|capability\)?$)|(interior|internal|indoor|cabin).*(v2l|vehicle.to.load)"),
    "v2l_external": ("External V2L", r"(v2l|vehicle.to.load).*(outside|exterior|external|outdoor|adapt[eo]r|charge port)|(exterior|external|outdoor).*(v2l|vehicle.to.load)"),
    "v2l_any": ("V2L (any)", r"v2l|vehicle.to.load"),
    "heated_front_seats": ("Heated front seats", r"heated (and ventilated )?(front )?seats?|front (and rear )?seats?[\s-]*heat"),
    "heated_rear_seats": ("Heated rear seats", r"heated (rear|outer rear) seats?|rear seats?( \(outer\))?[\s-]*heat"),
    "ventilated_seats": ("Ventilated front seats", r"(?<!rear )ventilated (front )?seats?|front seats?[\s-]*ventilated|cooled (front )?seats?"),
    "heated_steering_wheel": ("Heated steering wheel", r"heated steering|steering wheel[\s-]*heat"),
    "memory_seats": ("Driver seat memory", r"memory"),
    "electric_seats": ("Electric seat adjustment", r"(electric|power(ed)?)[^,]*seat|seat[^,]*(electric|power(ed)?)"),
    "glass_roof": ("Glass / panoramic roof", r"sunroof|glass roof|panoramic|vision roof"),
    "camera_360": ("360° camera", r"360|surround view|around view|svm"),
    "hud": ("Head-up display", r"head[- ]?up display|\bhud\b"),
    "powered_tailgate": ("Powered tailgate", r"(power(ed)?|electric|smart|hands.free)[^,]*tailgate|tailgate[^,]*(power|electric)"),
    "powered_sliding_doors": ("Powered sliding doors", r"(power(ed)?|electric)[^,]*sliding door|sliding door[^,]*(power|electric)"),
    "wireless_charging": ("Wireless phone charging", r"wireless (phone )?charg"),
    "adaptive_cruise": ("Adaptive cruise control", r"adaptive cruise|smart cruise|navigation.based smart cruise|highway drive"),
    "blind_spot": ("Blind-spot monitoring", r"blind.spot"),
    "led_headlights": ("LED headlights", r"led (head|projection)|full led"),
    "matrix_led": ("Adaptive / matrix headlights", r"matrix|adaptive (led|headlight|high beam)|intelligent front"),
    "digital_key": ("Digital key", r"digital key"),
    "tow_prep": ("Tow bar / towing prep", r"tow"),
    "keyless": ("Keyless entry", r"keyless|smart key|smart entry"),
    "rear_privacy_glass": ("Privacy glass", r"privacy glass|dark[- ]tinted|tinted (rear|privacy|side|tailgate)"),
    "leather": ("Leather / leatherette", r"leather"),
    "nav": ("Built-in navigation", r"navigation|sat nav|satnav"),
    "carplay": ("Apple CarPlay / Android Auto", r"carplay|android auto"),
    "bose_harman": ("Premium audio", r"bose|harman|krell|meridian|premium (sound|audio)"),
    # A socket in the car, not the three-pin charging cable (ICCB / mode 2) every EV ships with.
    "three_pin_socket": ("3-pin socket mentioned", r"^(?!.*(cable|connector|iccb|mode 2|charger|charging)).*(3.pin|three.pin|230v|220v|domestic socket)"),
}

_COMPILED = {k: re.compile(p, re.I) for k, (_, p) in FLAGS.items()}


def flags_for(standard: list[str], options: list[str] | None = None) -> dict[str, str | None]:
    """Canonical flag → 'standard' | 'option' | None. None means 'not listed', not
    'absent': sources list what a car has, rarely what it lacks."""
    std = [i.lower() for i in standard]
    opt = [i.lower() for i in options or []]
    out: dict[str, str | None] = {}
    for k, rx in _COMPILED.items():
        if any(rx.search(t) for t in std):
            out[k] = "standard"
        elif any(rx.search(t) for t in opt):
            out[k] = "option"
        else:
            out[k] = None
    return out


def matched_items(items: list[str], flag: str) -> list[str]:
    rx = _COMPILED[flag]
    return [i for i in items if rx.search(i.lower())]


# Wheel size in inches from an equipment item: '17" Alloy wheels', '19-inch diamond-cut alloys',
# 'Tyres - 235/55 R19'. Steering wheels, spare wheels, arches and wheelbases are not wheels.
WHEEL_ITEM_RE = re.compile(r"wheel|alloy|\brims?\b|tyre", re.I)
NOT_WHEEL_RE = re.compile(r"steering|spare|space.?saver|arch|wheelbase|drive|lock|nut|repair|pressure|tyre (?:inflation|mobility)", re.I)
INCH_RE = re.compile(r"(?<![\d.])(1[3-9]|2[0-3])(?:\.0)?\s*(?:\"|”|″|''|-?\s*inch(?:es)?\b|in\b)", re.I)
RIM_RE = re.compile(r"\bR\s?(1[3-9]|2[0-3])\b")


def wheel_sizes(items: list[str]) -> set[int]:
    """Every wheel size (inches) an equipment list names."""
    out: set[int] = set()
    for it in items or []:
        if not WHEEL_ITEM_RE.search(it) or NOT_WHEEL_RE.search(it):
            continue
        out.update(int(m.group(1)) for m in INCH_RE.finditer(it))
        out.update(int(m.group(1)) for m in RIM_RE.finditer(it))
    return out


def wheel_size(items: list[str]) -> int | None:
    """The one wheel size a standard-equipment list names; None when it names none, or several (per engine)."""
    sizes = wheel_sizes(items)
    return next(iter(sizes)) if len(sizes) == 1 else None
