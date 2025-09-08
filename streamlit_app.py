import streamlit as st
import geopandas as gpd
import pandas as pd
import plotly.express as px
import numpy as np
from matplotlib import cm, colors as mcolors

# ----------------------------------------------------
# Custom color palette
# ----------------------------------------------------
def set_palette(name="viridis", low=0, high=1, n=5):
    cmap = cm.get_cmap(name)
    cols = cmap(np.linspace(low, high, n))
    return [mcolors.to_hex(c) for c in cols]

palette = set_palette("viridis", low=0, high=1, n=5)

# ----------------------------------------------------
# Load data
# ----------------------------------------------------
gdf = gpd.read_file("data/geoBoundaries-IDN-ADM1_simplified.geojson")
df = pd.read_csv("data/icvi_results.csv")

# ----------------------------------------------------
# Streamlit UI
# ----------------------------------------------------
st.title("ICVI Dashboard")
st.subheader("Indonesia Provinces - ICVI Map")

# Year slider
year = st.slider("Select Year", int(df["year"].min()), int(df["year"].max()), int(df["year"].max()))
df_year = df[df["year"] == year]

# Merge by province name (adjust column names if needed)
merged = gdf.merge(df_year, left_on="shapeName", right_on="province")

# ----------------------------------------------------
# Plotly Choropleth
# ----------------------------------------------------
fig = px.choropleth(
    merged,
    geojson=merged.geometry,
    locations=merged.index,
    color="ICVI",
    hover_name="province",
    projection="mercator",
    color_continuous_scale=palette,
    range_color=[0.15, 0.63]  # fixed ICVI scale
)

fig.update_geos(fitbounds="locations", visible=False)
st.plotly_chart(fig, use_container_width=True)
