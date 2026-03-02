from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import date

from data import load_catalog
from planner import (
    Context,
    filter_variants,
    build_groups_from_variants,
    rank_groups,
    build_itinerary,
    attach_variants,
    insert_fillers,
)

app = FastAPI(title="Cairns AI Trip Planner")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ✅ Load Excel once at startup
catalog = load_catalog()
CATEGORY_STRUCTURE = {
    "Nature & Wildlife": [
        "Hiking",
        "Rainforest Walk",
        "Waterfall Visit",
        "Crocodile Encounter",
        "National Park Visit",
        "Aquarium",
        "Beach",
    ],
    "Tours & Cruises": [
        "Private tours",
        "Food Tours",
        "Aboriginal Cultural Tour",
        "River Cruise",
        "Cave Tours",
        "Island Tours",
        "Half Day Tours",
    ],
    "Adventure": [
        "Zipline",
        "Snorkelling",
        "Scuba Diving",
        "Whitewater Rafting",
        "Tubing",
        "Fishing",
        "Skydiving",
        "Kayaking",
    ],
    "Scenic Flights": [
        "Helicopter Flights",
        "Hot Air Balloon Flights",
        "Fly & Cruise",
    ],
    "Culture & History": [
        "Market Visit",
        "Museum Visit",
        "Art Gallery",
    ],
}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    df = catalog.variants

    # Build Must-Do and Subcat lists from the same sheet
    must_dos = []
    if "Cairns_must_do" in df.columns:
        must_dos = sorted([x for x in df["Cairns_must_do"].dropna().unique() if str(x).strip()])

    subcats = sorted(set(
        [x for x in df.get("primary_sub_category", []).dropna().tolist()] +
        [x for x in df.get("secondary_sub_category", []).dropna().tolist()] +
        [x for x in df.get("tertiary_sub_category", []).dropna().tolist()]
    ))

    return templates.TemplateResponse("index.html", {
        "request": request,
        "must_dos": must_dos,
        "category_structure": CATEGORY_STRUCTURE,
        "itinerary": None,
        "selected_must_dos": [],
        "selected_subcats": [],

    })


@app.post("/plan", response_class=HTMLResponse)
def plan(
    request: Request,
    start_date: str = Form(...),
    end_date: str = Form(...),
    adults: int = Form(2),
    children: int = Form(0),
    infants: int = Form(0),
    pensioners: int = Form(0),
    can_swim: str = Form("yes"),
    selected_must_dos: list[str] = Form([]),
    selected_subcats: list[str] = Form([]),
):
    ctx = Context(
        start_date=date.fromisoformat(start_date),
        end_date=date.fromisoformat(end_date),
        adults=adults,
        children=children,
        infants=infants,
        pensioners=pensioners,
        can_swim=(can_swim == "yes"),
        selected_must_dos=selected_must_dos,
        selected_subcats=selected_subcats,
    )

    # ✅ All logic happens inside the endpoint
    filtered_variants = filter_variants(catalog.variants, ctx)
    groups = build_groups_from_variants(filtered_variants)
    ranked = rank_groups(groups, ctx)
    itin = build_itinerary(ranked, ctx)
    itin = attach_variants(itin, filtered_variants, top_n=5)
    itin = insert_fillers(itin, catalog.fillers, max_fillers=2)

    # rebuild lists for template rendering
    df = catalog.variants
    must_dos = []
    if "Cairns_must_do" in df.columns:
        must_dos = sorted([x for x in df["Cairns_must_do"].dropna().unique() if str(x).strip()])

    subcats = sorted(set(
        [x for x in df.get("primary_sub_category", []).dropna().tolist()] +
        [x for x in df.get("secondary_sub_category", []).dropna().tolist()] +
        [x for x in df.get("tertiary_sub_category", []).dropna().tolist()]
    ))

    return templates.TemplateResponse("index.html", {
        "request": request,
        "must_dos": must_dos,
        "category_structure": CATEGORY_STRUCTURE,
        "itinerary": itin,
        "selected_must_dos": selected_must_dos,
        "selected_subcats": selected_subcats,
    })