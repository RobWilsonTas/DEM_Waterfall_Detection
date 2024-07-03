import time
from pathlib import Path
from datetime import datetime
startTime = time.time()


"""
##########################################################
User options
"""

#Initial variable assignment
inDEM               = 'D:/DEM.tif'           #E.g 'C:/Temp/DEM.tif', must be a 1m DEM
rainfallMMPerYear   = 'D:/Rainfall.tif'      #E.g 'C:/Temp/Rainfall.tif', must be a raster of rainfall in mm per year
streamLayer         = 'D:/StreamLines.gpkg'  #E.g 'C:/Temp/StreamLines.gpkg', this is used for culvert prediction
roadLayer           = 'D:/RoadLines.gpkg'    #E.g 'C:/Temp/RoadLines.gpkg', this is used for culvert prediction

#Options for compressing the images, ZSTD gives the best speed but LZW allows you to view the thumbnail in windows explorer
compressOptions     = 'COMPRESS=ZSTD|NUM_THREADS=ALL_CPUS|PREDICTOR=1|ZSTD_LEVEL=1|BIGTIFF=IF_SAFER|TILED=YES'
gdalOptions         = '--config GDAL_NUM_THREADS ALL_CPUS -overwrite'


"""
##########################################################
Set up some variables
"""

#Set up the layer name for the raster calculations
inDEMName = inDEM.split("/")
inDEMName = inDEMName[-1]
inDEMName = inDEMName[:len(inDEMName)-4]

rainfallName = rainfallMMPerYear.split("/")
rainfallName = rainfallName[-1]
rainfallName = rainfallName[:len(rainfallName)-4]

#Making a folder for processing
rootProcessDirectory = str(Path(inDEM).parent.absolute()).replace('\\','/') + '/'
processDirectory = rootProcessDirectory + inDEMName + 'DropsProcess' + '/'
if not os.path.exists(processDirectory):        os.mkdir(processDirectory)

#Get the pixel size and coordinate system of the raster
ras = QgsRasterLayer(inDEM)
pixelSizeX = ras.rasterUnitsPerPixelX()
pixelSizeY = ras.rasterUnitsPerPixelY()
rasExtent = ras.extent()
xminRas = rasExtent.xMinimum()
xmaxRas = rasExtent.xMaximum()
yminRas = rasExtent.yMinimum()
ymaxRas = rasExtent.yMaximum()
transformExtentParameter = '-projwin ' + str(xminRas) + ' ' + str(ymaxRas) + ' ' + str(xmaxRas) + ' ' + str(yminRas)


"""
##########################################################
Culvert dropping
"""

#Get the streams layer in the relevant area
processing.run("native:extractbyextent", {'INPUT':streamLayer,'EXTENT':rasExtent,'CLIP':False,'OUTPUT':processDirectory + 'StreamsClipped.gpkg'})

#Get the roads layer in the relevant area
processing.run("native:extractbyextent", {'INPUT':roadLayer,'EXTENT':rasExtent,'CLIP':False,'OUTPUT':processDirectory + 'RoadsClipped.gpkg'})

#Find where they intersect, i.e where the culverts are
processing.run("native:lineintersections", {'INPUT':processDirectory + 'StreamsClipped.gpkg','INTERSECT':processDirectory + 'RoadsClipped.gpkg','INPUT_FIELDS':[],'INTERSECT_FIELDS':[],
    'INTERSECT_FIELDS_PREFIX':'','OUTPUT':processDirectory + 'CulvertPoints.gpkg'})

#Buffer the points out
processing.run("native:buffer", {'INPUT':processDirectory + 'CulvertPoints.gpkg','DISTANCE':5,'SEGMENTS':5,'END_CAP_STYLE':0,'JOIN_STYLE':0,'MITER_LIMIT':2,'DISSOLVE':True,
    'OUTPUT':processDirectory + 'CulvertPointsBuffered.gpkg'})

#Turn this into a raster with a value of -1 where the culverts are
processing.run("gdal:rasterize", {'INPUT':processDirectory + 'CulvertPointsBuffered.gpkg','FIELD':'','BURN':-1,'UNITS':1,'WIDTH':pixelSizeX,'HEIGHT':pixelSizeY,
    'EXTENT':rasExtent,'NODATA':None,'OPTIONS':compressOptions,'DATA_TYPE':5,'INIT':None,'INVERT':False,'EXTRA':'','OUTPUT':processDirectory + 'CulvertPointsBufferedRasterised.tif'})

#Combine the DEM with the culvert dropping raster
processing.run("qgis:rastercalculator", {'EXPRESSION':'\"' + inDEMName + '@1\" + \"CulvertPointsBufferedRasterised@1\"','LAYERS':[inDEM,processDirectory + 'CulvertPointsBufferedRasterised.tif'],
    'CELLSIZE':0,'EXTENT':None,'CRS':None,'OUTPUT':processDirectory + 'DEMCulvertDropped.tif'})

"""
##########################################################
Main processing
"""

#Calculate flow accumulation 
processing.run("grass7:r.watershed", {'elevation':processDirectory + 'DEMCulvertDropped.tif','depression':None,'flow':None,'disturbed_land':None,'blocking':None,'threshold':5,'max_slope_length':5,'convergence':10,
    'memory':300,'-s':True,'-m':False,'-4':False,'-a':True,'-b':False,'accumulation':processDirectory + 'FlowAccumulation.tif','GRASS_REGION_PARAMETER':None,
    'GRASS_REGION_CELLSIZE_PARAMETER':0,'GRASS_RASTER_FORMAT_OPT':'','GRASS_RASTER_FORMAT_META':''})

#Make sure that the rainfall raster is in the right projection
processing.run("gdal:warpreproject", {'INPUT':rainfallMMPerYear,'SOURCE_CRS':None,'TARGET_CRS':QgsCoordinateReferenceSystem(ras.crs().authid()),
    'RESAMPLING':0,'NODATA':None,'TARGET_RESOLUTION':None,'OPTIONS':compressOptions,'DATA_TYPE':0,'TARGET_EXTENT':None,'TARGET_EXTENT_CRS':None,'MULTITHREADING':True,'EXTRA':'','OUTPUT':processDirectory + 'RainfallReproj.tif'})

#Resample it ready for the raster calculator
processing.run("gdal:translate", {'INPUT':processDirectory + 'RainfallReproj.tif','TARGET_CRS':None,'NODATA':None,'COPY_SUBDATASETS':False,'OPTIONS':compressOptions,
    'EXTRA':transformExtentParameter + ' -tr ' + str(pixelSizeX) + ' ' + str(pixelSizeY) + ' -r cubic','DATA_TYPE':0,'OUTPUT':processDirectory + 'RainfallReprojResamp.tif'})

#Multiply in the rainfall
processing.run("qgis:rastercalculator", {'EXPRESSION':'\"RainfallReprojResamp@1\" * \"FlowAccumulation@1\"','LAYERS':[processDirectory + 'FlowAccumulation.tif',processDirectory + 'RainfallReprojResamp.tif'],'CELLSIZE':0,'EXTENT':None,'CRS':None,
    'OUTPUT':processDirectory + 'FlowAccumulationPlusRain.tif'})

#Grab the DEM only along the streams
processing.run("qgis:rastercalculator", {'EXPRESSION':'\"' + inDEMName + '@1\" / (\"FlowAccumulationPlusRain@1\">15000000)','LAYERS':[processDirectory + 'FlowAccumulationPlusRain.tif',inDEM],'CELLSIZE':0,'EXTENT':None,'CRS':None,
    'OUTPUT':processDirectory + 'DEMAlongStream.tif'})

#Determine how much drop there is in the DEM within a 5m diameter
processing.run("grass7:r.neighbors", {'input':processDirectory + 'DEMAlongStream.tif','selection':processDirectory + 'DEMAlongStream.tif','method':5,'size':5,'gauss':None,
    'quantile':'','-c':True,'-a':False,'weight':'','output':processDirectory + 'DropAlong5m.tif','GRASS_REGION_PARAMETER':None,'GRASS_REGION_CELLSIZE_PARAMETER':0,'GRASS_RASTER_FORMAT_OPT':'',
    'GRASS_RASTER_FORMAT_META':''})

#Determine how much drop there is in the DEM within a 20m diameter
processing.run("grass7:r.neighbors", {'input':processDirectory + 'DEMAlongStream.tif','selection':processDirectory + 'DEMAlongStream.tif','method':5,'size':21,'gauss':None,
    'quantile':'','-c':True,'-a':False,'weight':'','output':processDirectory + 'DropAlong20m.tif','GRASS_REGION_PARAMETER':None,'GRASS_REGION_CELLSIZE_PARAMETER':0,'GRASS_RASTER_FORMAT_OPT':'',
    'GRASS_RASTER_FORMAT_META':''})
    
#Combine the two and give greater weight to a steeper drop
processing.run("qgis:rastercalculator", {'EXPRESSION':'\"DropAlong5m@1\" + ((\"DropAlong20m@1\" ^ 1.5)*0.08)','LAYERS':[processDirectory + 'DropAlong20m.tif',
    processDirectory + 'DropAlong5m.tif'],'CELLSIZE':0,'EXTENT':None,'CRS':None,'OUTPUT':processDirectory + 'CombinedDropFactor.tif'})
    
#Work out the score as a product of the size of the drop and the amount of water going over the drop
processing.run("qgis:rastercalculator", {'EXPRESSION':'(\"FlowAccumulationPlusRain@1\" ^ 0.2)  * \"CombinedDropFactor@1\"','LAYERS':[processDirectory + 'CombinedDropFactor.tif',
    processDirectory + 'FlowAccumulationPlusRain.tif'],'CELLSIZE':0,'EXTENT':None,'CRS':None,'OUTPUT':processDirectory + 'DropFactorPlusFlowAcc.tif'})

#Determine where the largest local score is
processing.run("grass7:r.neighbors", {'input':processDirectory + 'DropFactorPlusFlowAcc.tif','selection':processDirectory + 'DropFactorPlusFlowAcc.tif','method':4,'size':21,
    'gauss':None,'quantile':'','-c':True,'-a':False,'weight':'','output':processDirectory + 'DropFactorPlusFlowAccMaximum.tif','GRASS_REGION_PARAMETER':None,'GRASS_REGION_CELLSIZE_PARAMETER':0,
    'GRASS_RASTER_FORMAT_OPT':'','GRASS_RASTER_FORMAT_META':''})
    
#See if each pixel is the largest local drop
processing.run("qgis:rastercalculator", {'EXPRESSION':'\"DropFactorPlusFlowAcc@1\" / (\"DropFactorPlusFlowAcc@1\" = \"DropFactorPlusFlowAccMaximum@1\")',
    'LAYERS':[processDirectory + 'DropFactorPlusFlowAccMaximum.tif',processDirectory + 'DropFactorPlusFlowAcc.tif'],
    'CELLSIZE':0,'EXTENT':None,'CRS':None,'OUTPUT':processDirectory + 'DropFactorPlusFlowAccBiggest.tif'})

#Convert these pixels to points
processing.run("native:pixelstopoints", {'INPUT_RASTER':processDirectory + 'DropFactorPlusFlowAccBiggest.tif','RASTER_BAND':1,'FIELD_NAME':'DropValue',
    'OUTPUT':processDirectory + 'BiggestDropPoints.gpkg'})
    
"""
##########################################################
Point processing
"""
    
#Only get the points that have a decent score
processing.run("native:extractbyattribute", {'INPUT':processDirectory + 'BiggestDropPoints.gpkg','FIELD':'DropValue','OPERATOR':2,'VALUE':'604',
    'OUTPUT':processDirectory + 'BiggestDropPointsFilter.gpkg'})
    
#Add in the catchment values
processing.run("native:rastersampling", {'INPUT':processDirectory + 'BiggestDropPointsFilter.gpkg',
    'RASTERCOPY':processDirectory + 'FlowAccumulation.tif','COLUMN_PREFIX':'Catchment','OUTPUT':processDirectory + 'BiggestDropPointsFilterPlusCatchment.gpkg'})
    
#Add in the rainfall values
processing.run("native:rastersampling", {'INPUT':processDirectory + 'BiggestDropPointsFilterPlusCatchment.gpkg',
    'RASTERCOPY':processDirectory + 'RainfallReprojResamp.tif','COLUMN_PREFIX':'Rainfall','OUTPUT':processDirectory + 'BiggestDropPointsFilterPlusCatchmentPlusRainfall.gpkg'})
    
#Add in the drop along 5m values
processing.run("native:rastersampling", {'INPUT':processDirectory + 'BiggestDropPointsFilterPlusCatchmentPlusRainfall.gpkg',
    'RASTERCOPY':processDirectory + 'DropAlong5m.tif','COLUMN_PREFIX':'DropAlong5m','OUTPUT':processDirectory + 'BiggestDropPointsFilterPlusCatchmentPlusRainfallPlusDrop5.gpkg'})

#Add in the drop along 20m values and export as a final gpkg
processing.runAndLoadResults("native:rastersampling", {'INPUT':processDirectory + 'BiggestDropPointsFilterPlusCatchmentPlusRainfallPlusDrop5.gpkg',
    'RASTERCOPY':processDirectory + 'DropAlong20m.tif','COLUMN_PREFIX':'DropAlong20m','OUTPUT':rootProcessDirectory + inDEMName + 'WaterfallPoints.gpkg'})


"""
#######################################################################
"""

#All done
endTime = time.time()
totalTime = endTime - startTime
print("Done, this took " + str(int(totalTime)) + " seconds")
