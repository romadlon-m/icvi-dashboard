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
import matplotlib as mpl
import matplotlib.colors as mcolors

# ---------- Page ----------
st.set_page_config(page_title="ICVI Dashboard", layout="wide")
st.markdown(
    "#### ICVI — Integrated Climate Vulnerability Index"
    "&nbsp;&nbsp;·&nbsp;&nbsp;"
    "<span style='font-size:0.85rem;font-weight:400;color:gray;'>"
    "Explore provincial/regency ICVI by Average or Yearly (2014–2023)</span>",
    unsafe_allow_html=True,
)

# ---------- Paths ----------
ADM1_GEOJSON = Path("data/geoBoundaries-IDN-ADM1_simplified.geojson")
ADM2_GEOJSON = Path("data/geoBoundaries-IDN-ADM2_simplified.geojson")
ICVI_PROV_CSV = Path("data/icvi_results.csv")  # Indonesia (provincial)
ICVI_ADM2 = {
    "East Nusa Tenggara (NTT)": Path("data/NTT_icvi_results.csv"),
    "North Sulawesi (Sulut)":   Path("data/Sulut_icvi_results.csv"),
    "Yogyakarta (DIY)":         Path("data/DIY_icvi_results.csv"),
    "Kepulauan Bangka Belitung (Babel)": Path("data/Babel_icvi_results.csv"),
}

# ---------- Region metadata (centers/zooms) ----------
REGIONS = {
    "Indonesia": {"level": "ADM1", "center": [-2.0, 118.0], "zoom": 5},
    "East Nusa Tenggara (NTT)": {"level": "ADM2", "center": [-9.367410, 122.213088], "zoom": 7},
    "North Sulawesi (Sulut)":   {"level": "ADM2", "center": [2.651467, 125.414369], "zoom": 7},
    "Yogyakarta (DIY)":         {"level": "ADM2", "center": [-7.887551, 110.429646], "zoom": 10},
    "Kepulauan Bangka Belitung (Babel)": {"level": "ADM2", "center": [-2.5, 106.4], "zoom": 8},
}

# ---------- Top drivers (ADM1 only) ----------
# NOTE: lookup key is always lowercased via norm_name(), so only lowercase
# entries here are ever matched. Capitalized duplicates were dead code — removed.
TOP_DRIVERS = {
    "east nusa tenggara": "GRDP Agriculture; Population Growth; Population Density.",
    "nusa tenggara timur": "GRDP Agriculture; Population Growth; Population Density.",
    "north sulawesi": "GRDP Agriculture; Industrial & Service Scale; Population Growth.",
    "sulawesi utara": "GRDP Agriculture; Industrial & Service Scale; Population Growth.",
    "daerah istimewa yogyakarta": "Population Density; Economic Capacity; Industrial & Service Scale.",
    "di yogyakarta": "Population Density; Economic Capacity; Industrial & Service Scale.",
    "special region of yogyakarta": "Population Density; Economic Capacity; Industrial & Service Scale.",
    "yogyakarta": "Population Density; Economic Capacity; Industrial & Service Scale.",
    "kepulauan bangka belitung": "Population Density; GRDP Agriculture; GRDP Mining.",
    "babel": "Population Density; GRDP Agriculture; GRDP Mining.",
    "bangka-belitung islands": "Population Density; GRDP Agriculture; GRDP Mining.",
    "bangka belitung islands": "Population Density; GRDP Agriculture; GRDP Mining.",
}

# ---------- Palette (Viridis via matplotlib) ----------
# matplotlib.cm.get_cmap() was removed in matplotlib >=3.9.
# matplotlib.colormaps[name] works on matplotlib >=3.7, so this is the safe form.
def set_palette(name="viridis", low=0.0, high=1.0, n=256):
    cmap = mpl.colormaps[name]
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
    candidates = ["province"] if level == "ADM1" else ["regency"]
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
    n = n.replace("kota administrasi ", "kota ")
    n = n.replace("kota adm. ", "kota ")
    n = n.replace("-", " ").replace(".", " ")
    n = " ".join(n.split())
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
    for k in ["shapeName"]:
        if k in props:
            return k
    return next(iter(props.keys()), "shapeName")

def filter_adm2_by_names(gj2: dict, allowed_names_norm: set) -> dict:
    """Keep ADM2 features whose shapeName matches names from CSV."""
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

# ---------- Sidebar controls ----------
with st.sidebar:
    st.header("Filter Wilayah & Tahun")
    region = st.selectbox("Region", list(REGIONS.keys()), index=0)
    mode = st.radio("Mode", ["Average", "Yearly"], index=0)

    meta = REGIONS[region]
    level = meta["level"]
    df = load_csv(ICVI_PROV_CSV if region == "Indonesia" else ICVI_ADM2[region])
    name_col = detect_name_col(df, level)

    year = None
    if mode == "Yearly":
        if "year" not in df.columns or df["year"].isna().all():
            st.error("This dataset has no usable 'year' column for Yearly mode."); st.stop()
        years = sorted(int(y) for y in df["year"].dropna().unique())
        year = st.slider("Year", min_value=min(years), max_value=max(years), value=max(years), step=1)

    basemap_default = st.selectbox("Basemap", ["Esri Gray Canvas", "OpenStreetMap"], index=0)
    st.divider()
    st.caption("Data: FDES–DPSIR ICVI, 2014–2023")

# ---------- Select data for coloring ----------
if mode == "Yearly":
    source_df = df[df["year"] == year].copy()
    layer_name = f"ICVI {year}"
else:
    source_df = df.groupby(name_col, as_index=False, dropna=False)["ICVI"].mean()
    layer_name = "ICVI Average"

source_df[name_col] = source_df[name_col].astype(str)
icvi_lookup = {norm_name(r[name_col]): float(r["ICVI"]) for _, r in source_df.iterrows() if pd.notna(r["ICVI"])}

# ---------- Choose & build geometry ----------
if level == "ADM1":
    gj = gj_adm1
    popup_label = "Province:"
else:
    all_names_norm = {norm_name(x) for x in df[name_col].dropna().astype(str)}
    gj = filter_adm2_by_names(gj_adm2, all_names_norm)
    popup_label = "Regency/City:"

if not gj.get("features"):
    st.error("No boundaries found for this region. Ensure your ADM2 CSV names match GeoJSON 'shapeName'.")
    st.stop()

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
    if level == "ADM1":
        props["TopDrivers"] = TOP_DRIVERS.get(key, "—")

present_vals = [f["properties"]["ICVI"] for f in gj["features"] if f["properties"].get("ICVI") is not None]
vmin, vmax = dynamic_range(pd.Series(present_vals))

# ---------- Map + summary metrics (fits one 16:9 screen, no scroll) ----------
col_map, col_side = st.columns([3, 1])

with col_side:
    st.subheader(layer_name)
    if present_vals:
        vals_arr = np.array(present_vals)
        m1, m2 = st.columns(2)
        m1.metric("Mean", f"{vals_arr.mean():.3f}")
        m2.metric("Max", f"{vals_arr.max():.3f}")
        m1.metric("Min", f"{vals_arr.min():.3f}")

        max_idx = int(np.argmax(vals_arr))
        max_name = [f["properties"]["displayName"] for f in gj["features"]
                    if f["properties"].get("ICVI") is not None][max_idx]
        st.caption(f"Tertinggi: **{max_name}**")
    else:
        st.info("No numeric ICVI values for this selection.")

# ---------- Map ----------
with col_map:
    m = folium.Map(location=meta["center"], zoom_start=meta["zoom"], tiles=None, control_scale=True)
    inject_css_js_to_kill_focus(m)

    esri = folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Source: Esri, HERE, Garmin, FAO, NOAA, USGS, and others",
        name="Esri WorldGrayCanvas",
        control=True,
    )
    osm = folium.TileLayer("OpenStreetMap", name="OpenStreetMap", control=True)

    if basemap_default == "Esri Gray Canvas":
        esri.add_to(m); osm.add_to(m)
    else:
        osm.add_to(m); esri.add_to(m)

    colormap = LinearColormap(colors=PALETTE, vmin=vmin, vmax=vmax)
    colormap.caption = "ICVI Score"
    colormap.add_to(m)

    def style_fn(feature):
        v = feature["properties"].get("ICVI", None)
        if v is None:
            return {"fillColor": "#e5e7eb", "color": "#111827", "weight": 1, "fillOpacity": 0.25}
        return {"fillColor": colormap(v), "color": "#111827", "weight": 1, "fillOpacity": 0.75}

    popup_fields  = ["displayName", "ICVI_text"]
    popup_aliases = [popup_label, "ICVI:"]
    if level == "ADM1":
        popup_fields.append("TopDrivers")
        popup_aliases.append("Top drivers:")

    folium.GeoJson(
        data=gj,
        name=layer_name,
        style_function=style_fn,
        highlight_function=None,
        popup=folium.GeoJsonPopup(
            fields=popup_fields,
            aliases=popup_aliases,
            localize=True,
            labels=True,
            max_width=320,
        ),
    ).add_to(m)

    # collapsed=True + bottomleft: avoids overlapping the colormap legend (top area)
    folium.LayerControl(collapsed=True, position="bottomleft").add_to(m)

    st_folium(
        m,
        use_container_width=True,
        height=440,
        key="mainmap",
        returned_objects=[],  # click-only UX, no reruns on interaction
    )

# ---------- Data table (full width, below map — long columns fit) ----------
with st.expander("Data table", expanded=False):
    st.dataframe(source_df, use_container_width=True, height=260)
    st.download_button(
        "Download CSV",
        data=source_df.to_csv(index=False).encode("utf-8"),
        file_name=f"icvi_{region.split()[0].lower()}_{layer_name.replace(' ', '_').lower()}.csv",
        mime="text/csv",
    )