# streamlit_app.py
import json
from pathlib import Path

import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from branca.element import MacroElement, Template
from branca.colormap import LinearColormap

# ---------- Page ----------
st.set_page_config(page_title="ICVI Dashboard", layout="wide")
st.title("Indonesia — Integrated Climate Vulnerability Index (ICVI)")
st.caption("Explore provincial/regency ICVI by Average or Yearly (2014–2023).")

# ---------- Paths ----------
ADM1_GEOJSON = Path("data/geoBoundaries-IDN-ADM1_simplified.geojson")
ADM2_GEOJSON = Path("data/geoBoundaries-IDN-ADM2_simplified.geojson")
ICVI_PROV_CSV = Path("data/icvi_results.csv")  # Indonesia (provincial)
ICVI_ADM2 = {
    "East Nusa Tenggara (NTT)": Path("data/NTT_icvi_results.csv"),
    "North Sulawesi (Sulut)":   Path("data/Sulut_icvi_results.csv"),
    "Yogyakarta (DIY)":         Path("data/DIY_icvi_results.csv"),
}

# ---------- Region metadata (updated centers/zooms) ----------
REGIONS = {
    "Indonesia": {
        "level": "ADM1",
        "center": [-2.0, 118.0],
        "zoom": 5,
    },
    "East Nusa Tenggara (NTT)": {
        "level": "ADM2",
        "center": [-9.367410, 122.213088],  # NTT
        "zoom": 7,
    },
    "North Sulawesi (Sulut)": {
        "level": "ADM2",
        "center": [2.651467, 125.414369],   # North Sulawesi
        "zoom": 7,
    },
    "Yogyakarta (DIY)": {
        "level": "ADM2",
        "center": [-7.887551, 110.429646],  # Yogyakarta
        "zoom": 10,
    },
}

# ---------- Palette (Viridis via matplotlib) ----------
import matplotlib.cm as cm
import matplotlib.colors as mcolors

def set_palette(name="viridis", low=0.0, high=1.0, n=256):
    cmap = cm.get_cmap(name)
    cols = cmap(np.linspace(low, high, n))
    return [mcolors.to_hex(c) for c in cols]

PALETTE = set_palette("viridis", 0.0, 1.0, 256)

# ---------- Helpers ----------
@st.cache_data
def load_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    if "ICVI" in df.columns:
        df["ICVI"] = pd.to_numeric(df["ICVI"], errors="coerce")
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype(str).str.strip()
    return df

@st.cache_data
def load_geojson(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def detect_name_col(df: pd.DataFrame, level: str) -> str:
    if level == "ADM1":
        candidates = ["province", "provinsi", "name", "shapeName"]
    else:
        candidates = ["regency", "kabupaten_kota", "kab_kota", "kabupaten", "kota", "name", "shapeName", "adm2"]
    for c in candidates:
        if c in df.columns:
            return c
    for c in df.columns:
        if c.lower() not in {"year", "icvi"}:
            return c
    raise ValueError("Could not detect a name column in CSV.")

def norm_name(s: str) -> str:
    """Normalize names for matching (handles ADM2 'Kabupaten/Kota' prefixes & spacing)."""
    if not isinstance(s, str):
        return ""
    n = s.lower().strip()
    for pref in ["kabupaten ", "kab. ", "kab ", "kota ", "kota adm. ", "kota administrasi "]:
        if n.startswith(pref):
            n = n[len(pref):]
    repl = {
        " d.i. yogyakarta": " yogyakarta",
        "daerah istimewa yogyakarta": "yogyakarta",
        "special region of yogyakarta": "yogyakarta",
        "dki jakarta": "jakarta",
        "jakarta capital region": "jakarta",
        "bangka-belitung islands": "bangka belitung",
        "bangka belitung islands": "bangka belitung",
        "riau islands": "kepulauan riau",
        "-": " ",
        ".": " ",
        "  ": " ",
    }
    for k, v in repl.items():
        n = n.replace(k, v)
    n = " ".join(n.split())
    n = "".join(ch for ch in n if ch.isalnum())
    return n

def inject_css_js_to_kill_focus(m: folium.Map) -> None:
    css = MacroElement()
    css._template = Template("""
    {% macro html(this, kwargs) %}
    <style>
    .leaflet-interactive:focus,
    .leaflet-interactive:focus-visible { outline: none !important; outline-offset: 0 !important; }
    </style>
    {% endmacro %}
    """)
    m.get_root().add_child(css)

    js = MacroElement()
    js._template = Template("""
    {% macro script(this, kwargs) %}
    function __defocus__(){
      document.querySelectorAll('.leaflet-interactive').forEach(function(el){
        el.removeAttribute('tabindex');
        if (el.blur) el.blur();
      });
    }
    var map = {{ this._parent.get_name() }};
    map.on('layeradd', __defocus__);
    map.on('click', __defocus__);
    setTimeout(__defocus__, 300);
    {% endmacro %}
    """)
    m.get_root().add_child(js)

def dynamic_range(values: pd.Series) -> tuple[float, float]:
    vals = pd.to_numeric(values, errors="coerce").dropna()
    if vals.empty:
        return 0.0, 1.0
    vmin, vmax = float(vals.min()), float(vals.max())
    if np.isclose(vmin, vmax):
        pad = max(0.001, 0.05 * max(abs(vmax), 1e-6))
        return max(0.0, vmin - pad), min(1.0, vmax + pad)
    return vmin, vmax

def detect_geom_name_key(gj: dict) -> str:
    if not gj.get("features"):
        return "shapeName"
    props = gj["features"][0].get("properties", {})
    for k in ["shapeName", "NAME_2", "NAME_1", "name", "Name"]:
        if k in props:
            return k
    return next(iter(props.keys()), "shapeName")

def filter_adm2_by_names(gj2: dict, allowed_names_norm: set[str]) -> dict:
    """Option A: keep ADM2 features whose shapeName matches names from CSV."""
    feats = []
    for f in gj2.get("features", []):
        nm = f.get("properties", {}).get("shapeName", "")
        if norm_name(nm) in allowed_names_norm:
            feats.append(f)
    return {"type": "FeatureCollection", "features": feats}

# ---------- Load geometry ----------
if not ADM1_GEOJSON.exists():
    st.error(f"GeoJSON not found: {ADM1_GEOJSON.resolve()}"); st.stop()
if not ADM2_GEOJSON.exists():
    st.error(f"GeoJSON not found: {ADM2_GEOJSON.resolve()}"); st.stop()

gj_adm1 = load_geojson(ADM1_GEOJSON)
gj_adm2 = load_geojson(ADM2_GEOJSON)

# ---------- Controls ----------
region = st.selectbox("Region", list(REGIONS.keys()), index=0)  # default: Indonesia
mode = st.radio("Mode", ["Average", "Yearly"], horizontal=True, index=0)  # Average default

# Load ICVI data for selected region
meta = REGIONS[region]
level = meta["level"]

if region == "Indonesia":
    if not ICVI_PROV_CSV.exists():
        st.error(f"ICVI CSV not found: {ICVI_PROV_CSV.resolve()}"); st.stop()
    df = load_csv(ICVI_PROV_CSV)
else:
    path = ICVI_ADM2[region]
    if not path.exists():
        st.error(f"ICVI CSV not found: {path.resolve()}"); st.stop()
    df = load_csv(path)

name_col = detect_name_col(df, level)

# Year control only for Yearly mode
if mode == "Yearly":
    if "year" not in df.columns or df["year"].isna().all():
        st.error("This dataset has no usable 'year' column for Yearly mode."); st.stop()
    years = sorted([int(y) for y in df["year"].dropna().unique()])
    year = st.slider("Year", min_value=min(years), max_value=max(years), value=max(years), step=1)

# Select data for coloring
if mode == "Yearly":
    source_df = df[df["year"] == year].copy()
    layer_name = f"ICVI {year}"
else:
    source_df = df.groupby(name_col, as_index=False, dropna=False)["ICVI"].mean()
    layer_name = "ICVI Average"

# Build lookup by normalized name (for current view)
source_df[name_col] = source_df[name_col].astype(str)
icvi_lookup = {norm_name(r[name_col]): float(r["ICVI"]) for _, r in source_df.iterrows() if pd.notna(r["ICVI"])}

# ---------- Choose & build geometry ----------
if level == "ADM1":
    gj = gj_adm1
    popup_label = "Province:"
else:
    # Option A: filter ADM2 by all regency names present in the region CSV (across years)
    all_names_norm = {norm_name(x) for x in df[name_col].dropna().astype(str)}
    gj = filter_adm2_by_names(gj_adm2, all_names_norm)
    popup_label = "Regency/City:"

# Guard: empty geometry
if not gj.get("features"):
    st.error("No boundaries found for this region. Ensure your ADM2 CSV names match GeoJSON 'shapeName'.")
    st.stop()

# Detect geometry name key & attach displayName + ICVI fields
geom_name_key = detect_geom_name_key(gj)
missing_geom = []
missing_csv  = []

geom_names_norm_set = {norm_name(f["properties"].get(geom_name_key, "")) for f in gj["features"]}
for csv_nm in (source_df[name_col].dropna().astype(str)):
    if norm_name(csv_nm) not in geom_names_norm_set:
        missing_csv.append(csv_nm)

for feat in gj["features"]:
    props = feat.setdefault("properties", {})
    disp = props.get(geom_name_key) or props.get("shapeName") or props.get("name") or "Unknown"
    props["displayName"] = disp
    key = norm_name(disp)
    val = icvi_lookup.get(key)
    if val is None or pd.isna(val):
        missing_geom.append(disp)
        props["ICVI"] = None
        props["ICVI_text"] = "No data"
    else:
        props["ICVI"] = float(val)
        props["ICVI_text"] = f"{val:.3f}"

# Dynamic color range based on values present on the map
present_vals = [f["properties"]["ICVI"] for f in gj["features"] if f["properties"].get("ICVI") is not None]
vmin, vmax = dynamic_range(pd.Series(present_vals))

# ---------- Map ----------
m = folium.Map(location=meta["center"], zoom_start=meta["zoom"], tiles=None, control_scale=True)
inject_css_js_to_kill_focus(m)

# Basemaps (default = Esri WorldGrayCanvas)
folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)  # add first
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    attr="Tiles © Esri — Source: Esri, HERE, Garmin, FAO, NOAA, USGS, and others",
    name="Esri WorldGrayCanvas",
    control=True,
).add_to(m)  # added last so it is active by default

# Color scale + caption
colormap = LinearColormap(colors=PALETTE, vmin=vmin, vmax=vmax)
colormap.caption = "ICVI Score"
colormap.add_to(m)

def style_fn(feature):
    v = feature["properties"].get("ICVI", None)
    if v is None:
        return {"fillColor": "#e5e7eb", "color": "#111827", "weight": 1, "fillOpacity": 0.25}
    return {"fillColor": colormap(v), "color": "#111827", "weight": 1, "fillOpacity": 0.75}

folium.GeoJson(
    data=gj,
    name=layer_name,
    style_function=style_fn,
    highlight_function=None,  # click-only UX
    popup=folium.GeoJsonPopup(
        fields=["displayName", "ICVI_text"],
        aliases=[popup_label, "ICVI:"],
        localize=True,
        labels=True,
        max_width=320,
    ),
).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

# ---------- Render (disable reruns on click) ----------
st_folium(
    m,
    use_container_width=True,
    height=640,
    key="mainmap",
    returned_objects=[],  # <- disables callbacks so clicks won't rerun the app
)

# ---------- Diagnostics ----------
with st.expander("Name mismatches (helpful if something doesn't color)"):
    if level == "ADM2":
        st.write("**CSV names not found in ADM2 geometry:**")
        st.write(sorted(set(missing_csv)) or "—")
    st.write("**Geometry names with no ICVI in current view:**")
    st.write(sorted(set(missing_geom)) or "—")
