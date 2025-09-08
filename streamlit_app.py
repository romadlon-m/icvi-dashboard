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
ICVI_PROV_CSV = Path("data/icvi_results.csv")          # Indonesia (provinces)
ICVI_ADM2 = {
    "East Nusa Tenggara (NTT)": Path("data/NTT_icvi_results.csv"),
    "North Sulawesi (Sulut)":   Path("data/Sulut_icvi_results.csv"),
    "Yogyakarta (DIY)":         Path("data/DIY_icvi_results.csv"),
}

# ---------- Region metadata ----------
REGIONS = {
    "Indonesia": {
        "level": "ADM1",
        "center": [-2.0, 118.0],
        "zoom": 5,
        "shapeGroup": None,   # not used at ADM1
    },
    "East Nusa Tenggara (NTT)": {
        "level": "ADM2",
        "center": [-9.3, 123.7],
        "zoom": 6,
        "shapeGroup": "Nusa Tenggara Timur",
    },
    "North Sulawesi (Sulut)": {
        "level": "ADM2",
        "center": [1.3, 124.8],
        "zoom": 7,
        "shapeGroup": "Sulawesi Utara",
    },
    "Yogyakarta (DIY)": {
        "level": "ADM2",
        "center": [-7.8, 110.4],
        "zoom": 8,
        "shapeGroup": "Daerah Istimewa Yogyakarta",
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
    # normalize common column names
    if "year" in df.columns:
        df["year"] = df["year"].astype(int)
    if "ICVI" in df.columns:
        df["ICVI"] = pd.to_numeric(df["ICVI"], errors="coerce")
    return df

@st.cache_data
def load_geojson(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def detect_name_col(df: pd.DataFrame, level: str) -> str:
    """Find the column holding the area name (province or regency)."""
    candidates = (
        ["province", "provinsi", "name", "shapeName"] if level == "ADM1"
        else ["regency", "kabupaten_kota", "kab_kota", "kabupaten", "kota", "name", "shapeName", "adm2"]
    )
    for c in candidates:
        if c in df.columns:
            return c
    # fallback to first non-year/non-value column
    for c in df.columns:
        if c.lower() not in {"year", "icvi"}:
            return c
    raise ValueError("Could not detect a name column in CSV.")

def norm_name(s: str) -> str:
    if not isinstance(s, str):
        return ""
    n = s.lower().strip()
    # remove common Indo prefixes for ADM2
    for pref in ["kabupaten ", "kab. ", "kab ", "kota ", "kota adm. ", "kota administrasi "]:
        if n.startswith(pref):
            n = n[len(pref):]
    # harmonize spaces & punctuation
    repl = {
        "dki jakarta": "jakarta",
        "jakarta capital region": "jakarta",
        "daerah istimewa yogyakarta": "yogyakarta",
        "special region of yogyakarta": "yogyakarta",
        "bangka-belitung islands": "bangka belitung",
        "bangka belitung islands": "bangka belitung",
        "riau islands": "kepulauan riau",
        "-": " ",
        "  ": " ",
    }
    for k, v in repl.items():
        n = n.replace(k, v)
    return " ".join(n.split())  # collapse spaces

def inject_css_js_to_kill_focus(m: folium.Map) -> None:
    css = MacroElement()
    css._template = Template("""
    {% macro html(this, kwargs) %}
    <style>
    .leaflet-interactive:focus,
    .leaflet-interactive:focus-visible {
        outline: none !important;
        outline-offset: 0 !important;
    }
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

def filter_adm2_by_province(gj2: dict, shape_group_name: str) -> dict:
    feats = [f for f in gj2["features"] if f["properties"].get("shapeGroup") == shape_group_name]
    return {"type": "FeatureCollection", "features": feats}

# ---------- Load geometry ----------
if not ADM1_GEOJSON.exists():
    st.error(f"GeoJSON not found: {ADM1_GEOJSON.resolve()}"); st.stop()
if not ADM2_GEOJSON.exists():
    st.error(f"GeoJSON not found: {ADM2_GEOJSON.resolve()}"); st.stop()

gj_adm1 = load_geojson(ADM1_GEOJSON)
gj_adm2 = load_geojson(ADM2_GEOJSON)

# ---------- Controls ----------
region = st.selectbox(
    "Region",
    list(REGIONS.keys()),
    index=0  # default: Indonesia
)
mode = st.radio("Mode", ["Average", "Yearly"], horizontal=True, index=0)  # Average first & default

# load data for selected region
region_meta = REGIONS[region]
level = region_meta["level"]

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
df[name_col] = df[name_col].astype(str).str.strip()

if mode == "Yearly":
    if "year" not in df.columns:
        st.error("This dataset has no 'year' column for Yearly mode."); st.stop()
    years = sorted(df["year"].unique().tolist())
    year = st.slider("Year", min_value=min(years), max_value=max(years), value=max(years), step=1)

# select data
if mode == "Yearly":
    source_df = df[df["year"] == year].copy()
    layer_name = f"ICVI {year}"
else:
    avg_df = df.groupby(name_col, as_index=False)["ICVI"].mean()
    source_df = avg_df.copy()
    layer_name = "ICVI Average"

# build lookup by normalized name
icvi_lookup = {norm_name(r[name_col]): float(r["ICVI"]) for _, r in source_df.iterrows()}

# choose geometry per region
if level == "ADM1":
    gj = gj_adm1
    popup_label = "Province:"
else:
    gj = filter_adm2_by_province(gj_adm2, region_meta["shapeGroup"])
    popup_label = "Regency/City:"

# inject ICVI into geometry props
missing = []
for feat in gj["features"]:
    name = feat["properties"].get("shapeName", "")
    key = norm_name(name)
    val = icvi_lookup.get(key)
    if val is None or pd.isna(val):
        missing.append(name)
        feat["properties"]["ICVI"] = None
        feat["properties"]["ICVI_text"] = "No data"
    else:
        feat["properties"]["ICVI"] = float(val)
        feat["properties"]["ICVI_text"] = f"{val:.3f}"

present_vals = [f["properties"]["ICVI"] for f in gj["features"] if f["properties"].get("ICVI") is not None]
vmin, vmax = dynamic_range(pd.Series(present_vals))

# ---------- Map ----------
m = folium.Map(location=region_meta["center"], zoom_start=region_meta["zoom"], tiles=None, control_scale=True)
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
        fields=["shapeName", "ICVI_text"],
        aliases=[popup_label, "ICVI:"],
        localize=True,
        labels=True,
        max_width=320,
    ),
).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
st_folium(m, use_container_width=True, height=640)

# diagnostics
if missing:
    with st.expander("Unmatched names (CSV vs GeoJSON)"):
        st.write(sorted(set(missing)))
        st.caption("Extend norm_name() or adjust your CSV labels if needed.")
