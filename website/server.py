#!/usr/bin/env python3
"""
Sample healthcare website — doctor search/browse, doctor detail, appointment booking,
and an appointments cart. A real, server-rendered web app (no client-side JS needed) so
kane-cli's browser automation has an actual UI to assure, matching the pattern of the
retail-assurance-demo's public ecommerce-playground target — except this one is started
in-job (see the workflow's "evidence" job) rather than already hosted somewhere.

All doctors, slots, and fees are synthetic. requirements/healthcare-website.md documents
this app's behavior exactly — keep both in sync if either changes.
"""

from __future__ import annotations

import os

from flask import Flask, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("WEBSITE_SECRET_KEY", "dev-secret-change-me")

APPOINTMENT_TYPES = ["New Patient", "Follow-up"]

DOCTORS = [
    {"id": "cruz", "name": "Dr. Elena Cruz", "specialty": "Cardiology", "fee": 180, "rating": 4.8,
     "bio": "Board-certified cardiologist focused on preventive heart health.",
     "slots": ["2026-09-21 09:00", "2026-09-21 14:00", "2026-09-22 10:00"]},
    {"id": "webb", "name": "Dr. Marcus Webb", "specialty": "Cardiology", "fee": 165, "rating": 4.6,
     "bio": "Specializes in arrhythmia management and cardiac rehabilitation.",
     "slots": ["2026-09-21 11:00", "2026-09-22 09:00", "2026-09-23 15:00"]},
    {"id": "nandy", "name": "Dr. Priya Nandy", "specialty": "Dermatology", "fee": 140, "rating": 4.9,
     "bio": "Treats acne, eczema, and skin cancer screening.",
     "slots": ["2026-09-21 10:00", "2026-09-22 13:00", "2026-09-23 09:00"]},
    {"id": "baxter", "name": "Dr. Owen Baxter", "specialty": "Dermatology", "fee": 130, "rating": 4.5,
     "bio": "Cosmetic and general dermatology for all ages.",
     "slots": ["2026-09-21 15:00", "2026-09-22 11:00", "2026-09-23 10:00"]},
    {"id": "alvarez", "name": "Dr. Sofia Alvarez", "specialty": "Pediatrics", "fee": 120, "rating": 4.7,
     "bio": "General pediatric care from infancy through adolescence.",
     "slots": ["2026-09-21 09:30", "2026-09-22 14:00", "2026-09-23 11:00"]},
    {"id": "chen", "name": "Dr. Liam Chen", "specialty": "Pediatrics", "fee": 110, "rating": 4.4,
     "bio": "Focuses on childhood development and vaccinations.",
     "slots": ["2026-09-21 13:00", "2026-09-22 09:30", "2026-09-23 14:00"]},
    {"id": "kim", "name": "Dr. Grace Kim", "specialty": "Orthopedics", "fee": 200, "rating": 4.6,
     "bio": "Sports medicine and joint injury specialist.",
     "slots": ["2026-09-21 08:00", "2026-09-22 15:00", "2026-09-23 08:00"]},
    {"id": "holt", "name": "Dr. Derek Holt", "specialty": "Orthopedics", "fee": 190, "rating": 4.3,
     "bio": "Spine and back pain treatment, non-surgical first.",
     "slots": ["2026-09-21 16:00", "2026-09-22 08:00", "2026-09-23 16:00"]},
    {"id": "osei", "name": "Dr. Nia Osei", "specialty": "General Medicine", "fee": 100, "rating": 4.8,
     "bio": "Primary care and annual wellness visits.",
     "slots": ["2026-09-21 09:00", "2026-09-22 10:00", "2026-09-23 13:00"]},
    {"id": "novak", "name": "Dr. Peter Novak", "specialty": "General Medicine", "fee": 95, "rating": 4.5,
     "bio": "Same-day primary care and chronic condition management.",
     "slots": ["2026-09-21 14:30", "2026-09-22 16:00", "2026-09-23 09:30"]},
    {"id": "patel", "name": "Dr. Asha Patel", "specialty": "General Medicine", "fee": 105, "rating": 4.6,
     "bio": "Comprehensive adult primary care and chronic disease management.",
     "slots": ["2026-09-21 10:30", "2026-09-22 11:30", "2026-09-23 15:30"]},
    {"id": "reyes", "name": "Dr. Carlos Reyes", "specialty": "General Medicine", "fee": 90, "rating": 4.2,
     "bio": "Walk-in friendly primary and preventive care.",
     "slots": ["2026-09-21 12:00", "2026-09-22 13:30", "2026-09-23 16:30"]},
]
DOCTORS_BY_ID = {d["id"]: d for d in DOCTORS}
SPECIALTIES = sorted({d["specialty"] for d in DOCTORS})

# Slots already booked (by anyone) — shared, in-memory, resets when the process restarts.
# Simulates a limited real calendar so double-booking is a real, testable condition.
booked_slots: set[tuple[str, str]] = set()


def available_slots(doctor: dict) -> list[str]:
    return [s for s in doctor["slots"] if (doctor["id"], s) not in booked_slots]


def cart() -> list[dict]:
    return session.setdefault("cart", [])


@app.context_processor
def inject_globals():
    return {"specialties": SPECIALTIES, "cart_count": len(cart())}


@app.get("/")
def home():
    return render_template("home.html")


@app.get("/search")
def search():
    q = (request.args.get("q") or "").strip().lower()
    results = [d for d in DOCTORS if q and (q in d["name"].lower() or q in d["specialty"].lower())]
    return render_template("search_results.html", query=request.args.get("q", ""), results=results)


@app.get("/specialty/<name>")
def specialty(name: str):
    doctors = [d for d in DOCTORS if d["specialty"].lower() == name.lower()]
    if not doctors:
        return render_template("listing.html", specialty_name=name, doctors=[], view="grid", sort="name"), 404

    sort_key = request.args.get("sort", "name")
    if sort_key == "fee":
        doctors = sorted(doctors, key=lambda d: d["fee"])
    elif sort_key == "rating":
        doctors = sorted(doctors, key=lambda d: -d["rating"])
    else:
        sort_key = "name"
        doctors = sorted(doctors, key=lambda d: d["name"])

    try:
        per_page = int(request.args.get("per_page", 6))
    except ValueError:
        per_page = 6
    view = request.args.get("view", "grid")
    if view not in ("grid", "list"):
        view = "grid"

    return render_template(
        "listing.html",
        specialty_name=doctors[0]["specialty"],
        doctors=doctors[:per_page],
        total=len(doctors),
        sort=sort_key,
        per_page=per_page,
        view=view,
    )


@app.get("/doctor/<doctor_id>")
def doctor_detail(doctor_id: str):
    doctor = DOCTORS_BY_ID.get(doctor_id)
    if not doctor:
        return "Doctor not found", 404
    # Every slot is listed, taken ones included and marked unavailable — a taken slot
    # must still be a selectable option so a patient (or a test) can attempt to book it
    # and see the real rejection, rather than it silently disappearing from the list.
    slot_rows = [
        {"time": s, "available": (doctor["id"], s) not in booked_slots}
        for s in doctor["slots"]
    ]
    return render_template(
        "doctor_detail.html",
        doctor=doctor,
        slot_rows=slot_rows,
        appointment_types=APPOINTMENT_TYPES,
        error=request.args.get("error"),
    )


@app.post("/book")
def book():
    doctor_id = request.form.get("doctor_id", "")
    doctor = DOCTORS_BY_ID.get(doctor_id)
    if not doctor:
        return "Doctor not found", 404

    appointment_type = request.form.get("appointment_type", "")
    slot = request.form.get("slot", "")

    if not appointment_type:
        return redirect(url_for("doctor_detail", doctor_id=doctor_id,
                                 error="Please select an appointment type before booking."))
    if not slot or (doctor_id, slot) in booked_slots or slot not in doctor["slots"]:
        return redirect(url_for("doctor_detail", doctor_id=doctor_id,
                                 error="That slot is no longer available. Please choose another."))

    booked_slots.add((doctor_id, slot))
    entry = {
        "doctor_id": doctor_id,
        "doctor_name": doctor["name"],
        "specialty": doctor["specialty"],
        "slot": slot,
        "appointment_type": appointment_type,
        "fee": doctor["fee"],
    }
    c = cart()
    c.append(entry)
    session["cart"] = c
    session["last_booked"] = entry
    return redirect(url_for("doctor_detail", doctor_id=doctor_id))


@app.get("/appointments")
def appointments():
    items = cart()
    total = sum(item["fee"] for item in items)
    return render_template("cart.html", items=items, total=total)


@app.post("/appointments/cancel/<int:index>")
def cancel_appointment(index: int):
    items = cart()
    if 0 <= index < len(items):
        entry = items.pop(index)
        booked_slots.discard((entry["doctor_id"], entry["slot"]))
        session["cart"] = items
    return redirect(url_for("appointments"))


@app.get("/contact")
def contact():
    return render_template("contact.html")


# Test-fixture seeding only — not part of the product surface. Books one or more
# appointments into the CALLING browser's own session (same cookie jar) before
# redirecting, so a kane-cli scenario can arrive at a page with pre-existing
# appointments by navigating here first, instead of being told to "book this
# yourself" in prose (which the agent doesn't reliably act on — see README).
# `book` repeats as doctor_id:slot:appointment_type, `:` and `,`-separated.
@app.get("/dev/seed")
def dev_seed():
    for entry in request.args.getlist("book"):
        doctor_id, slot, appointment_type = entry.split(":", 2)
        doctor = DOCTORS_BY_ID.get(doctor_id)
        if not doctor or (doctor_id, slot) in booked_slots:
            continue
        booked_slots.add((doctor_id, slot))
        c = cart()
        c.append({
            "doctor_id": doctor_id,
            "doctor_name": doctor["name"],
            "specialty": doctor["specialty"],
            "slot": slot,
            "appointment_type": appointment_type,
            "fee": doctor["fee"],
        })
        session["cart"] = c
    return redirect(request.args.get("next", "/"))


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
