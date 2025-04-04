This script runs in QGIS

This takes in a DEM and other layers to automatically detect where there are waterfalls

It asks for a rainfall raster, to help understand where there would be more water, and therefore a better waterfall

It also asks for a road and a streams layer. These are used to estimate where there might be a culvert, allowing water to flow across the DEM in a realistic way, instead of getting stuck in table drains

_____________

The process involves adding iterations of noise to the DEM, then calculating where the flow accumulation is

In areas of significant flow accumulation it calculates how much the flow drops in elevation

Any spots where there are both significant flow and significant elevation drop are marked as waterfall points
