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

# ---------------- Config ----------------
st.set_page_config(page_title="ICVI Dashboard", layout="wide")
st.title("Indonesia ICVI — Provinces (ADM1)")

ICVI_MIN = 0.15
ICVI_MAX = 0.63

GEOJSON_PATH = Path("data/geoBoundaries-IDN-ADM1_simplified.geojson")
ICVI_CSV     = Path("data/icvi_results.csv")

# ---------------- Palette (your function) ----------------
import matplotlib.cm as cm
import matplotlib.colors as mcolors

def set_palette(name="viridis", low=0.15, high=0.80, n=5):
    cmap = cm.get_cmap(name)
    cols = cmap(np.linspace(low, high, n))
    return [mcolors.to_hex(c) for c in cols]

# smooth gradient (256 steps) across full Viridis range
PALETTE = set_palette("viridis", low=0.0, high=1.0, n=256)

# ---------------- Helpers ----------------
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
    if not isinstance(name, str):
        return ""
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

# ---------------- Load data ----------------
if not GEOJSON_PATH.exists():
    st.error(f"GeoJSON not found: {GEOJSON_PATH.resolve()}"); st.stop()
if not ICVI_CSV.exists():
    st.error(f"ICVI CSV not found: {ICVI_CSV.resolve()}"); st.stop()

df = load_icvi(ICVI_CSV)
gj = load_geojson(GEOJSON_PATH)

# ---------------- UI ----------------
years = sorted(df["year"].unique().tolist())
year = st.slider("Year", min_value=min(years), max_value=max(years),
                 value=max(years), step=1)

# ---------------- Prepare selected year ----------------
year_df = df[df["year"] == year].copy()
icvi_lookup = {norm_name(r["province"]): float(r["ICVI"]) for _, r in year_df.iterrows()}

missing = []
for feat in gj["features"]:
    prov = feat["properties"].get("shapeName", "")
    key = norm_name(prov)
    val = icvi_lookup.get(key)
    if val is None:
        missing.append(prov)
    feat["properties"]["ICVI"] = None if val is None else float(val)
    feat["properties"]["ICVI_text"] = "No data" if val is None else f"{val:.3f}"

# ---------------- Map ----------------
m = folium.Map(location=[-2, 118], zoom_start=5, tiles="CartoDB positron", control_scale=True)
inject_css_js_to_kill_focus(m)

# Build a continuous colormap from your palette with fixed vmin/vmax
colormap = LinearColormap(colors=PALETTE, vmin=ICVI_MIN, vmax=ICVI_MAX)
colormap.caption = "ICVI (fixed scale 0.15–0.63)"
colormap.add_to(m)

def style_fn(feature):
    v = feature["properties"].get("ICVI", None)
    if v is None:
        return {"fillColor": "#e5e7eb", "color": "#111827", "weight": 1, "fillOpacity": 0.2}
    return {"fillColor": colormap(v), "color": "#111827", "weight": 1, "fillOpacity": 0.7}

folium.GeoJson(
    data=gj,
    name=f"ICVI {year}",
    style_function=style_fn,
    highlight_function=lambda f: {"weight": 2, "color": "#2563eb", "fillOpacity": 0.85},
    tooltip=folium.GeoJsonTooltip(fields=["shapeName", "ICVI_text"],
                                  aliases=["Province:", "ICVI:"], sticky=True),
    popup=folium.GeoJsonPopup(fields=["shapeName", "ICVI_text"],
                              aliases=["Province:", "ICVI:"], localize=True, labels=True),
).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
st_folium(m, use_container_width=True, height=640)

# Show any name mismatches so you can patch norm_name()
if missing:
    with st.expander("Unmatched province names (CSV vs GeoJSON)"):
        st.write(sorted(set(missing)))
