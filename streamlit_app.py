import streamlit as st
import geopandas as gpd
import pandas as pd
import plotly.express as px

# Load GeoJSON (province boundaries)
gdf = gpd.read_file("data/geoBoundaries-IDN-ADM1_simplified.geojson")

# Load ICVI results
df = pd.read_csv("data/icvi_results.csv")

# Year slider
year = st.slider("Select Year", int(df["year"].min()), int(df["year"].max()), int(df["year"].max()))
df_year = df[df["year"] == year]

# Merge by province name (adjust column names as needed)
merged = gdf.merge(df_year, left_on="shapeName", right_on="province")

# Plot choropleth
fig = px.choropleth(
    merged,
    geojson=merged.geometry,
    locations=merged.index,
    color="ICVI",
    hover_name="province",
    projection="mercator",
    color_continuous_scale="YlOrRd"
)

fig.update_geos(fitbounds="locations", visible=False)
st.plotly_chart(fig, use_container_width=True)
