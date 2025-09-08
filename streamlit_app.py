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

# ---------- Region metadata (centers/zooms) ----------
REGIONS = {
    "Indonesia": {"level": "ADM1", "center": [-2.0, 118.0], "zoom": 5},
    "East Nusa Tenggara (NTT)": {"level": "ADM2", "center": [-9.367410, 122.213088], "zoom": 7},
    "North Sulawesi (Sulut)":   {"level": "ADM2", "center": [2.651467, 125.414369], "zoom": 7},
    "Yogyakarta (DIY)":         {"level": "ADM2", "center": [-7.887551, 110.429646], "zoom": 10},
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
        candidates = ["province"]
    else:
        candidates = ["regency"]
    for c in candidates:
        if c in df.columns:
            return c
    for c in df.columns:
        if c.lower() not in {"year", "icvi"}:
            return c
    raise ValueError("Could not detect a name column in CSV.")

def norm_name(s: str) -> str:
    """Keep 'kota' to differentiate from regency."""
    if not isinstance(s, str):
        return ""
    n = s.strip().lower()

    # Standardize 'kota' variants ONLY (do NOT strip 'kota', and do NOT touch 'kabupaten').
    n = n.replace("kota administrasi ", "kota ")
    n = n.replace("kota adm. ", "kota ")

    # Light cleanup (spacing/punctuation), but keep words intact.
    n = n.replace("-", " ").replace(".", " ")
    n = " ".join(n.split())

    return n


from branca.element import MacroElement, Template
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
    for k in ["shapeName"]:
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
with st.spinner("Loading boundaries..."):
    if not ADM1_GEOJSON.exists():
        st.error(f"GeoJSON not found: {ADM1_GEOJSON.resolve()}"); st.stop()
    if not ADM2_GEOJSON.exists():
        st.error(f"GeoJSON not found: {ADM2_GEOJSON.resolve()}"); st.stop()
    gj_adm1 = load_geojson(ADM1_GEOJSON)
    gj_adm2 = load_geojson(ADM2_GEOJSON)

# ---------- Controls ----------
region = st.selectbox("Region", list(REGIONS.keys()), index=0)  # default: Indonesia
mode = st.radio("Mode", ["Average", "Yearly"], horizontal=True, index=0)  # Average default

# ---------- Load ICVI early so the Year slider can sit right under Mode ----------
meta  = REGIONS[region]
level = meta["level"]

with st.spinner("Loading ICVI data..."):
    df = load_csv(ICVI_PROV_CSV if region == "Indonesia" else ICVI_ADM2[region])

name_col = detect_name_col(df, level)

# ---------- Year slider (immediately after Mode) ----------
year = None
if mode == "Yearly":
    if "year" not in df.columns or df["year"].isna().all():
        st.error("This dataset has no usable 'year' column for Yearly mode."); st.stop()
    years = sorted([int(y) for y in df["year"].dropna().unique()])
    year = st.slider("Year", min_value=min(years), max_value=max(years), value=max(years), step=1)

# ---------- Map placeholder + progress (they come AFTER the slider) ----------
map_container = st.empty()
progress = st.progress(0, text="Preparing data...")

# ---------- Select data for coloring ----------
if mode == "Yearly":
    source_df = df[df["year"] == year].copy()
    layer_name = f"ICVI {year}"
else:
    source_df = df.groupby(name_col, as_index=False, dropna=False)["ICVI"].mean()
    layer_name = "ICVI Average"

source_df[name_col] = source_df[name_col].astype(str)
icvi_lookup = {norm_name(r[name_col]): float(r["ICVI"]) for _, r in source_df.iterrows() if pd.notna(r["ICVI"])}

progress.progress(45, text="Filtering boundaries...")

# ---------- Choose & build geometry ----------
if level == "ADM1":
    gj = gj_adm1
    popup_label = "Province:"
else:
    all_names_norm = {norm_name(x) for x in df[name_col].dropna().astype(str)}
    gj = filter_adm2_by_names(gj_adm2, all_names_norm)
    popup_label = "Regency/City:"

if not gj.get("features"):
    progress.empty()
    st.error("No boundaries found for this region. Ensure your ADM2 CSV names match GeoJSON 'shapeName'.")
    st.stop()

progress.progress(65, text="Styling & coloring...")

# Attach displayName + ICVI fields
geom_name_key = detect_geom_name_key(gj)
for feat in gj["features"]:
    props = feat.setdefault("properties", {})
    disp = props.get(geom_name_key) or props.get("shapeName") or props.get("name") or "Unknown"
    props["displayName"] = disp
    key = norm_name(disp)
    val = icvi_lookup.get(key)
    if val is None or pd.isna(val):
        props["ICVI"] = None
        props["ICVI_text"] = "No data"
    else:
        props["ICVI"] = float(val)
        props["ICVI_text"] = f"{val:.3f}"

present_vals = [f["properties"]["ICVI"] for f in gj["features"] if f["properties"].get("ICVI") is not None]
vmin, vmax = dynamic_range(pd.Series(present_vals))

progress.progress(85, text="Rendering map...")

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
).add_to(m)  # active by default

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
with map_container.container():
    st_folium(
        m,
        use_container_width=True,
        height=640,
        key="mainmap",
        returned_objects=[],  # stops callbacks so clicks won't rerun the app
    )

progress.progress(100, text="Done")
progress.empty()


# ---------DEBUG
if level == "ADM2":
    st.subheader(f"Regency/City list for {region}")

    # List from CSV
    csv_names = sorted(df[name_col].dropna().unique().tolist())
    st.markdown("**From CSV:**")
    st.write(csv_names)

    # List from GeoJSON (only the regencies in that province CSV, using your normalizer)
    gj_names = [f["properties"].get("shapeName", "") for f in gj_adm2["features"]]
    gj_names = sorted(set(gj_names))
    st.markdown("**From GeoJSON (all ADM2 features):**")
    st.write(gj_names)

    # Quick matched subset (those in both)
    matched = sorted(set(csv_names) & set(gj_names))
    st.markdown("**Matched names:**")
    st.write(matched)

    # Unmatched
    st.markdown("**CSV not in GeoJSON:**")
    st.write(sorted(set(csv_names) - set(gj_names)))

    st.markdown("**GeoJSON not in CSV:**")
    st.write(sorted(set(gj_names) - set(csv_names)))

