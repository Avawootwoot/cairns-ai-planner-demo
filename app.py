from fastapi import FastAPI, Request, Form, Body
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from datetime import date
import json
import re

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

# ✅ Session storage (cart, etc.)
# NOTE: change this secret key in real use
app.add_middleware(SessionMiddleware, secret_key="CHANGE_ME_TO_A_LONG_RANDOM_SECRET")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ✅ Load Excel once at startup
catalog = load_catalog()

CATEGORY_STRUCTURE = {
    "Nature & Wildlife": [
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
        "Outback Tours",
        "Island Tours",
        "Half Day Tours",
    ],
    "Adventure": [
        "Snorkelling",
        "Scuba Diving",
        "Whitewater Rafting",
        "Tubing",
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


def build_must_dos():
    df = catalog.variants
    must_dos = []
    if "Cairns_must_do" in df.columns:
        must_dos = sorted(
            [x for x in df["Cairns_must_do"].dropna().unique() if str(x).strip()]
        )
    return must_dos


def parse_chat_command(text: str) -> dict:
    t = text.strip().lower()

    # “remove day 3”
    m = re.search(r"\bremove\s+day\s+(\d+)\b", t)
    if m:
        return {"action": "remove_day", "day": int(m.group(1))}

    # “add a day for beach”
    m = re.search(r"\badd\s+(?:a\s+)?day\s+(?:for|to)\s+(.+)$", t)
    if m:
        theme = m.group(1).strip(" .!")
        return {"action": "add_day", "theme": theme}

    # “on day 2 replace with kuranda”
    m = re.search(
        r"\bon\s+day\s+(\d+)\s+(?:i\s+want\s+to\s+)?(?:replace|swap|change)\s+(?:it\s+)?(?:with|to)\s+(.+)$",
        t,
    )
    if m:
        return {
            "action": "replace_day",
            "day": int(m.group(1)),
            "query": m.group(2).strip(" .!"),
        }

    return {"action": "unknown", "raw": text}


def apply_edit_operation(itinerary: list, op: dict) -> list:
    """Demo-level edits. Later, you can swap this out for real replanning."""
    action = op.get("action")

    if action == "remove_day":
        idx = op["day"] - 1
        if 0 <= idx < len(itinerary):
            itinerary.pop(idx)
        return itinerary

    if action == "add_day":
        theme = op.get("theme", "New")
        itinerary.append(
            {
                "date": "New day",
                "anchor_group": {"title": f"{theme.title()} Day", "duration_hours": 4},
                "variants": [],
                "fillers": [],
                "filler_note": "",
            }
        )
        return itinerary

    if action == "replace_day":
        idx = op["day"] - 1
        query = op.get("query", "").strip()
        if 0 <= idx < len(itinerary) and itinerary[idx].get("anchor_group"):
            itinerary[idx]["anchor_group"]["title"] = (
                query.title() if query else "Updated Activity"
            )
        return itinerary

    return itinerary


def _safe_str(x):
    if x is None:
        return None
    s = str(x).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def lookup_variant(product_id: str) -> dict | None:
    """
    Look up a variant row by id from catalog.variants and return a dict
    with the fields your UI needs.
    """
    df = catalog.variants
    if "id" not in df.columns:
        return None

    pid_raw = _safe_str(product_id)
    if not pid_raw:
        return None

    # try numeric match first, then string match
    try:
        pid_int = int(float(pid_raw))
        row_df = df[df["id"] == pid_int]
        if row_df.empty:
            row_df = df[df["id"].astype(str) == str(pid_int)]
    except Exception:
        row_df = df[df["id"].astype(str) == pid_raw]

    if row_df.empty:
        return None

    row = row_df.iloc[0].to_dict()

    return {
        "product_id": _safe_str(row.get("id")),
        "title": _safe_str(row.get("title")) or _safe_str(row.get("name")) or "Untitled",
        "image_url": _safe_str(row.get("image_url")),
        "adult_price": _safe_str(row.get("adult_price")),
        "child_price": _safe_str(row.get("child_price")),
        # your excel column name:
        "duration_hours": row.get("duration in hours"),
    }


def get_cart(request: Request) -> dict:
    return request.session.get("cart", {"items": []})


def save_cart(request: Request, cart: dict) -> None:
    request.session["cart"] = cart


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "must_dos": build_must_dos(),
            "category_structure": CATEGORY_STRUCTURE,
            "itinerary": None,
            "itinerary_json": "",
            "selected_must_dos": [],
            "selected_subcats": [],
            # keep these for form defaults if you want:
            "start_date": "",
            "end_date": "",
            "adults": 2,
            "children": 0,
            "infants": 0,
            "pensioners": 0,
            "can_swim": "yes",
        },
    )


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

    filtered_variants = filter_variants(catalog.variants, ctx)
    groups = build_groups_from_variants(filtered_variants)
    ranked = rank_groups(groups, ctx)
    itin = build_itinerary(ranked, ctx)
    itin = attach_variants(itin, filtered_variants, top_n=5)
    itin = insert_fillers(itin, catalog.fillers, max_fillers=2)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "must_dos": build_must_dos(),
            "category_structure": CATEGORY_STRUCTURE,
            "itinerary": itin,
            "itinerary_json": json.dumps(itin, default=str),
            "selected_must_dos": selected_must_dos,
            "selected_subcats": selected_subcats,
            # preserve form values:
            "start_date": start_date,
            "end_date": end_date,
            "adults": adults,
            "children": children,
            "infants": infants,
            "pensioners": pensioners,
            "can_swim": can_swim,
        },
    )


@app.post("/chat_edit", response_class=HTMLResponse)
def chat_edit(
    request: Request,
    chat_message: str = Form(...),
    itinerary_json: str = Form(""),
    # Round-trip original inputs:
    start_date: str = Form(""),
    end_date: str = Form(""),
    adults: int = Form(2),
    children: int = Form(0),
    infants: int = Form(0),
    pensioners: int = Form(0),
    can_swim: str = Form("yes"),
    selected_must_dos: list[str] = Form([]),
    selected_subcats: list[str] = Form([]),
):
    # 1) Load itinerary
    try:
        itin = json.loads(itinerary_json) if itinerary_json else []
    except Exception:
        itin = []

    # 2) Parse chat -> operation
    op = parse_chat_command(chat_message)

    # 3) Apply operation (demo logic)
    itin = apply_edit_operation(itin, op)

    # 4) AI-style reply (demo-friendly)
    if op.get("action") == "replace_day":
        reply = f"Done — updated Day {op['day']} to “{op.get('query','').title()}”."
    elif op.get("action") == "add_day":
        reply = f"Done — added a new day for “{op.get('theme','').title()}”."
    elif op.get("action") == "remove_day":
        reply = f"Done — removed Day {op['day']}."
    else:
        reply = (
            "I didn’t understand that. Try: “On day 2 replace with …”, "
            "“Add a day for …”, or “Remove day 3”."
        )

    # 5) If called by the floating widget via fetch(), return JSON
    if request.query_params.get("format") == "json":
        return JSONResponse(
            {
                "reply": reply,
                "op": op,
                "itinerary_json": json.dumps(itin, default=str),
            }
        )

    # 6) Otherwise, render HTML normally
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "must_dos": build_must_dos(),
            "category_structure": CATEGORY_STRUCTURE,
            "itinerary": itin,
            "itinerary_json": json.dumps(itin, default=str),
            "selected_must_dos": selected_must_dos,
            "selected_subcats": selected_subcats,
            # preserve form values:
            "start_date": start_date,
            "end_date": end_date,
            "adults": adults,
            "children": children,
            "infants": infants,
            "pensioners": pensioners,
            "can_swim": can_swim,
            # chat history
            "last_chat_message": chat_message,
            "last_chat_op": op,
            "last_chat_reply": reply,
        },
    )


# ================================
# CART: add / view / update
# ================================

@app.post("/cart/add")
def cart_add(
    request: Request,
    product_id: str = Form(...),
    day_index: int = Form(0),
):
    cart = get_cart(request)

    info = lookup_variant(product_id)
    if info is None:
        # still store minimal info so demo doesn't break
        info = {"product_id": str(product_id), "title": f"Product {product_id}"}

    item = {
        **info,
        "day_index": int(day_index),
    }

    cart["items"].append(item)
    save_cart(request, cart)

    return RedirectResponse(url="/cart", status_code=303)


@app.get("/cart", response_class=HTMLResponse)
def cart_page(request: Request):
    cart = get_cart(request)
    # NOTE: you need templates/cart.html created
    return templates.TemplateResponse(
        "cart.html",
        {
            "request": request,
            "cart": cart,
        },
    )


@app.post("/cart/update")
def cart_update(request: Request, payload: dict = Body(...)):
    """
    Expected payload:
    { "moves": [ {"product_id":"4483","day_index":2}, ... ] }
    """
    cart = get_cart(request)
    items = cart.get("items", [])

    moves = payload.get("moves", [])
    index_by_pid = {}
    for i, it in enumerate(items):
        pid = str(it.get("product_id"))
        index_by_pid[pid] = i

    for mv in moves:
        pid = str(mv.get("product_id"))
        if pid in index_by_pid:
            items[index_by_pid[pid]]["day_index"] = int(mv.get("day_index", 0))

    cart["items"] = items
    save_cart(request, cart)
    return {"ok": True, "cart": cart}