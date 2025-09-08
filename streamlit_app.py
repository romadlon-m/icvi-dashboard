import streamlit as st
import geemap.foliumap as geemap
import ee

# Authenticate Earth Engine (use service account for Streamlit Cloud)
ee.Initialize()

st.title("ICVI Dashboard - Indonesia Map")

# Create a map centered on Indonesia
m = geemap.Map(center=[-2, 118], zoom=4)

# Load GAUL (you can use EE datasets)
gaul = ee.FeatureCollection("FAO/GAUL/2015/level1")  # Provinces
indo = gaul.filter(ee.Filter.eq("ADM0_NAME", "Indonesia"))

# Add to map
m.addLayer(indo, {}, "Indonesia Provinces")

# Display in Streamlit
m.to_streamlit(width=800, height=600)

