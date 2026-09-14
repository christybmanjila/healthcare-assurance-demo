# Riverbend Clinic — Release Requirements

**Product:** Riverbend Clinic patient-facing website (sample)
**Environment under test:** the bundled sample website (`website/server.py`), run locally
in the workflow at `http://localhost:5050`
**Release:** demo / pipeline validation
**Owner:** Solutions Engineering

> This document is the single source of truth `kane-cli context ingest`/`design tests`
> work from. It's written to match `website/server.py` exactly (verified by hand, see the
> commit that added it), so scenarios kane-cli designs from it are ones the sample site can
> actually pass or meaningfully fail — keep the two in sync if either changes. All data is
> synthetic; never point this pipeline at a real patient-facing site or real PHI without
> redoing this doc for the real thing.

---

## REQ-01 — Doctor search

Patients must be able to find a doctor by name or specialty from any page.

Acceptance criteria:
- The search box is present in the header on every page.
- Searching a term that matches a doctor's name or specialty (e.g. "Cardiology") returns
  a results grid with at least one doctor tile, and each tile shows the doctor's name,
  specialty, and consultation fee.
- Searching a term with no matches shows an explicit "No doctors match your search"
  message rather than an empty page or an error.
- Search results are reachable via a shareable URL (the search term appears as a `q`
  query parameter in the address bar).

## REQ-02 — Specialty browse and refinement

Patients must be able to browse a specialty and change how results are presented.

Acceptance criteria:
- Opening a specialty from the home page or nav opens a listing page showing a doctor
  count and a grid of doctor tiles.
- The listing offers a sort control (name A-Z, fee low-to-high, rating high-to-low) and
  the first doctor shown changes when the sort order changes.
- The listing offers a "show N per page" control, and choosing a smaller value reduces
  the number of tiles rendered.
- Switching between grid and list view keeps the same doctors on screen.

## REQ-03 — Doctor profile and appointment booking

The doctor detail page must give a patient enough to decide, and must book the correct
appointment.

Acceptance criteria:
- Opening a doctor from a listing or search result shows the doctor's name, specialty,
  consultation fee, rating, and a short bio.
- Booking without selecting an appointment type is rejected with a message telling the
  patient to select one; no appointment is added.
- Booking a valid, currently-open time slot with an appointment type succeeds, shows a
  confirmation naming the doctor, time, and appointment type, and updates the header's
  "My Appointments" count.
- Attempting to book a time slot that has already been booked (by this patient or anyone
  else) is rejected with a message that the slot is no longer available; no second
  appointment is created for that slot.

## REQ-04 — Appointments cart integrity

The appointments list must reflect exactly what the patient booked, and must survive
cancellations.

Acceptance criteria:
- The "My Appointments" page lists every booked appointment with doctor name, specialty,
  time, appointment type, and fee.
- The total estimated cost shown equals the sum of the listed fees.
- Canceling an appointment removes it from the list, updates the total, and makes that
  time slot bookable again for any doctor's page that offers it.
- With zero appointments, the page shows an explicit "no upcoming appointments" message.

## REQ-05 — Safety disclosures

Acceptance criteria:
- An emergency banner ("call 911 or go to your nearest emergency room") is visible on
  every page.
- Every doctor detail page shows a disclaimer that the profile is informational and does
  not constitute medical advice.
- The contact page shows office hours and a phone number.

---

Add REQ-NN sections here — and matching logic in `website/server.py` — before pointing
this pipeline at a different or more capable site.
