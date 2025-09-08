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
st.caption("Explore provincial ICVI by Yearly or Average (2014–2023).")


# ---------- Paths ----------
GEOJSON_PATH = Path("data/geoBoundaries-IDN-ADM1_simplified.geojson")
ICVI_CSV     = Path("data/icvi_results.csv")

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
def load_icvi(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]
    df["province"] = df["province"].astype(str).str.strip()
    df["year"] = df["year"].astype(int)
    df["ICVI"] = pd.to_numeric(df["ICVI"], errors="coerce")
    return df

@st.cache_data
def load_geojson(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def norm_name(name: str) -> str:
    if not isinstance(name, str): return ""
    n = name.strip().lower()
    replacements = {
        "dki jakarta": "jakarta",
        "jakarta capital region": "jakarta",
        "daerah istimewa yogyakarta": "yogyakarta",
        "special region of yogyakarta": "yogyakarta",
        "bangka-belitung islands": "bangka belitung",
        "bangka belitung islands": "bangka belitung",
        "riau islands": "kepulauan riau",
    }
    return replacements.get(n, n)

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

# ---------- Load ----------
if not GEOJSON_PATH.exists():
    st.error(f"GeoJSON not found: {GEOJSON_PATH.resolve()}"); st.stop()
if not ICVI_CSV.exists():
    st.error(f"ICVI CSV not found: {ICVI_CSV.resolve()}"); st.stop()

df = load_icvi(ICVI_CSV)
gj = load_geojson(GEOJSON_PATH)

# ---------- Controls ----------
mode = st.radio("Mode", ["Yearly", "Average"], horizontal=True, index=1)

if mode == "Yearly":
    years = sorted(df["year"].unique().tolist())
    year = st.slider("Year", min_value=min(years), max_value=max(years),
                     value=max(years), step=1)

# ---------- Select data ----------
if mode == "Yearly":
    source_df = df[df["year"] == year].copy()
    layer_name = f"ICVI {year}"
else:
    avg_df = df.groupby("province", as_index=False)["ICVI"].mean()
    source_df = avg_df.copy()
    layer_name = "ICVI Average"

# Build lookup
icvi_lookup = {norm_name(r["province"]): float(r["ICVI"])
               for _, r in source_df.iterrows()}

# Merge into GeoJSON
missing = []
for feat in gj["features"]:
    prov = feat["properties"].get("shapeName", "")
    key = norm_name(prov)
    val = icvi_lookup.get(key)
    if val is None or pd.isna(val):
        missing.append(prov)
        feat["properties"]["ICVI"] = None
        feat["properties"]["ICVI_text"] = "No data"
    else:
        feat["properties"]["ICVI"] = float(val)
        feat["properties"]["ICVI_text"] = f"{val:.3f}"

present_vals = [f["properties"]["ICVI"] for f in gj["features"] if f["properties"].get("ICVI") is not None]
vmin, vmax = dynamic_range(pd.Series(present_vals))

# ---------- Map ----------
m = folium.Map(location=[-2, 118], zoom_start=5, tiles=None, control_scale=True)
inject_css_js_to_kill_focus(m)

# Basemaps (default = Esri WorldGrayCanvas)
folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)  # add first
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    attr="Tiles © Esri — Source: Esri, HERE, Garmin, FAO, NOAA, USGS, and others",
    name="Esri WorldGrayCanvas",
    control=True,
).add_to(m)  # add last so it is active by default

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
        aliases=["Province:", "ICVI:"],
        localize=True,
        labels=True,
        max_width=320,
    ),
).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

st_folium(m, use_container_width=True, height=640)

if missing:
    with st.expander("Unmatched province names (CSV vs GeoJSON)"):
        st.write(sorted(set(missing)))
        st.caption("If needed, extend norm_name() to map differing labels.")
