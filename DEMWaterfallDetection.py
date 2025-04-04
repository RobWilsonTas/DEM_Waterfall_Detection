import time
from pathlib import Path
from datetime import datetime
startTime = time.time()


"""
##########################################################
User options
"""

#Initial variable assignment
inDEM               = 'C:/Temp/TestDEM.tif'               #E.g 'C:/Temp/DEM.tif'
rainfallMMPerYear   = 'C:/Temp/Average Rainfall.tif'      #E.g 'C:/Temp/Rainfall.tif', must be a raster of rainfall in mm per year
streamLayer         = 'C:/Temp/StreamLines.gpkg'          #E.g 'C:/Temp/StreamLines.gpkg', this is used for culvert prediction
roadLayer           = 'C:/Temp/RoadLines.gpkg'            #E.g 'C:/Temp/RoadLines.gpkg', this is used for culvert prediction

numberOfIterations  = 4 #Must be between 1 and 6
assignedRam         = 8000 #In MB

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
rasCrs = ras.crs().authid()
rasExtentParameter = str(xminRas) + ',' + str(xmaxRas) + ',' + str(yminRas) + ',' + str(ymaxRas) + ' [' + rasCrs + ']'
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
processing.run("native:buffer", {'INPUT':processDirectory + 'CulvertPoints.gpkg','DISTANCE':8,'SEGMENTS':5,'END_CAP_STYLE':0,'JOIN_STYLE':0,'MITER_LIMIT':2,'DISSOLVE':True,
    'OUTPUT':processDirectory + 'CulvertPointsBuffered.gpkg'})

#Turn this into a raster with a value of -1 where the culverts are
processing.run("gdal:rasterize", {'INPUT':processDirectory + 'CulvertPointsBuffered.gpkg','FIELD':'','BURN':-1,'UNITS':1,'WIDTH':pixelSizeX,'HEIGHT':pixelSizeY,
    'EXTENT':rasExtent,'NODATA':None,'OPTIONS':compressOptions,'DATA_TYPE':5,'INIT':None,'INVERT':False,'EXTRA':'','OUTPUT':processDirectory + 'CulvertPointsBufferedRasterised.tif'})

#Combine the DEM with the culvert dropping raster
processing.run("gdal:rastercalculator", {'INPUT_A':inDEM,'BAND_A':1,'INPUT_B':processDirectory + 'CulvertPointsBufferedRasterised.tif','BAND_B':1,
    'FORMULA':'A + B','NO_DATA':-1,'EXTENT_OPT':0,'PROJWIN':None,'RTYPE':5,'OPTIONS':compressOptions,'EXTRA':'','OUTPUT':processDirectory + 'DEMCulvertDropped.tif'})

"""
##########################################################
Adding noise to the DEM for each iteration
"""

for x in range (1,numberOfIterations + 1):
    
    #Create a raster of noise
    processing.run("native:createrandomnormalrasterlayer", {'EXTENT':rasExtentParameter,'TARGET_CRS':QgsCoordinateReferenceSystem(rasCrs),'PIXEL_SIZE':pixelSizeX,'OUTPUT_TYPE':0,'MEAN':0,'STDDEV':0.3,
        'OUTPUT':processDirectory + 'RandomRas' + str(x) + '.tif'})

    #Add it into the DEM
    processing.run("gdal:rastercalculator", {'INPUT_A':processDirectory + 'DEMCulvertDropped.tif','BAND_A':1,'INPUT_B':processDirectory + 'RandomRas' + str(x) + '.tif','BAND_B':1,'BAND_C':1,
        'FORMULA':'A + B','NO_DATA':-1,'EXTENT_OPT':0,'PROJWIN':None,'RTYPE':5,'OPTIONS':compressOptions,'EXTRA':'','OUTPUT':processDirectory + 'DEMCulvertDroppedRandom' + str(x) + '.tif'})

    #Calculate flow accumulation 
    processing.run("grass7:r.watershed", {'elevation':processDirectory + 'DEMCulvertDroppedRandom' + str(x) + '.tif','depression':None,'flow':None,'disturbed_land':None,'blocking':None,'threshold':5,'max_slope_length':5,'convergence':10,
        'memory':assignedRam,'-s':True,'-m':True,'-4':False,'-a':True,'-b':False,'accumulation':processDirectory + 'FlowAccumulation' + str(x) + '.tif','GRASS_REGION_PARAMETER':None,
        'GRASS_REGION_CELLSIZE_PARAMETER':0,'GRASS_RASTER_FORMAT_OPT':'','GRASS_RASTER_FORMAT_META':''})


"""
##########################################################
Preparing variables for the flow accumulation combination based on the number of iterations requested
"""
inputB = None
inputC = None
inputD = None
inputE = None
inputF = None

inputA = processDirectory + 'FlowAccumulation1.tif'

if numberOfIterations > 1:
    inputB = processDirectory + 'FlowAccumulation2.tif'

if numberOfIterations > 2:
    inputC = processDirectory + 'FlowAccumulation3.tif'

if numberOfIterations > 3:
    inputD = processDirectory + 'FlowAccumulation4.tif'

if numberOfIterations > 4:
    inputE = processDirectory + 'FlowAccumulation5.tif'

if numberOfIterations > 5:
    inputF = processDirectory + 'FlowAccumulation6.tif'


if numberOfIterations == 1:
    addFormula = 'A'
elif numberOfIterations == 2:
    addFormula = 'numpy.maximum(A, B)'
elif numberOfIterations == 3:
    addFormula = 'numpy.maximum(numpy.maximum(A, B), C)'
elif numberOfIterations == 4:
    addFormula = 'numpy.maximum(numpy.maximum(numpy.maximum(A, B), C), D)'
elif numberOfIterations == 5:
    addFormula = 'numpy.maximum(numpy.maximum(numpy.maximum(numpy.maximum(A, B), C), D), E)'
elif numberOfIterations == 6:
    addFormula = 'numpy.maximum(numpy.maximum(numpy.maximum(numpy.maximum(numpy.maximum(A, B), C), D), E), F)'

"""
##########################################################
Main processing
"""

#Find the maximum of the flow accumulation rasters, to determine where all possible stream paths are
processing.run("gdal:rastercalculator", {'INPUT_A':inputA,'BAND_A':1,'INPUT_B':inputB,'BAND_B':1,'INPUT_C':inputC,'BAND_C':1,'INPUT_D':inputD,'BAND_D':1,'INPUT_E':inputE,'BAND_E':1,'INPUT_F':inputF,'BAND_F':1,
        'FORMULA':addFormula,'NO_DATA':-1,'EXTENT_OPT':0,'PROJWIN':None,'RTYPE':5,'OPTIONS':compressOptions,'EXTRA':'','OUTPUT':processDirectory + 'CombinedFlowAccumulation.tif'})

#Make sure that the rainfall raster is in the right projection
processing.run("gdal:warpreproject", {'INPUT':rainfallMMPerYear,'SOURCE_CRS':None,'TARGET_CRS':QgsCoordinateReferenceSystem(ras.crs().authid()),
    'RESAMPLING':0,'NODATA':None,'TARGET_RESOLUTION':None,'OPTIONS':compressOptions,'DATA_TYPE':0,'TARGET_EXTENT':None,'TARGET_EXTENT_CRS':None,'MULTITHREADING':True,'EXTRA':'','OUTPUT':processDirectory + 'RainfallReproj.tif'})

#Resample it ready for the raster calculator
processing.run("gdal:translate", {'INPUT':processDirectory + 'RainfallReproj.tif','TARGET_CRS':None,'NODATA':None,'COPY_SUBDATASETS':False,'OPTIONS':compressOptions,
    'EXTRA':transformExtentParameter + ' -tr ' + str(pixelSizeX) + ' ' + str(pixelSizeY) + ' -r cubic','DATA_TYPE':0,'OUTPUT':processDirectory + 'RainfallReprojResamp.tif'})

#Multiply in the rainfall
processing.run("gdal:rastercalculator", {'INPUT_A': processDirectory + 'RainfallReprojResamp.tif','BAND_A': 1,'INPUT_B': processDirectory + 'CombinedFlowAccumulation.tif','BAND_B': 1,'INPUT_C': None,'BAND_C': -1,'INPUT_D': None,'BAND_D': -1,'INPUT_E': None,'BAND_E': -1,'INPUT_F': None,'BAND_F': -1,
'FORMULA': 'A * B * ' + str(pixelSizeX ** 2),'NO_DATA': None,'RTYPE': 5,'EXTRA': '','OPTIONS': compressOptions,'EXTENT_OPT': 0,'PROJWIN': None,'OUTPUT': processDirectory + 'FlowAccumulationPlusRain.tif'})

#Grab the DEM only along the streams (i.e where the flow accumulation is at least half decent)
processing.run("gdal:rastercalculator", {'INPUT_A': inDEM,'BAND_A': 1,'INPUT_B': processDirectory + 'FlowAccumulationPlusRain.tif','BAND_B': 1,'INPUT_C': None,'BAND_C': -1,'INPUT_D': None,'BAND_D': -1,'INPUT_E': None,'BAND_E': -1,'INPUT_F': None,'BAND_F': -1,
    'FORMULA': 'A * (B > 15000000)','NO_DATA':0,'RTYPE': 5,'EXTRA': '','OPTIONS': compressOptions,'EXTENT_OPT': 0,'PROJWIN': None,    'OUTPUT': processDirectory + 'DEMAlongStream.tif'})

#Determine how much drop there is in the DEM within a 5m diameter
processing.run("grass7:r.neighbors", {'input':processDirectory + 'DEMAlongStream.tif','selection':processDirectory + 'DEMAlongStream.tif','method':5,'size':5,'gauss':None,
    'quantile':'','-c':True,'-a':False,'weight':'','output':processDirectory + 'DropAlong5m.tif','GRASS_REGION_PARAMETER':None,'GRASS_REGION_CELLSIZE_PARAMETER':0,'GRASS_RASTER_FORMAT_OPT':'',
    'GRASS_RASTER_FORMAT_META':''})

#Determine how much drop there is in the DEM within a 20m diameter
processing.run("grass7:r.neighbors", {'input':processDirectory + 'DEMAlongStream.tif','selection':processDirectory + 'DEMAlongStream.tif','method':5,'size':21,'gauss':None,
    'quantile':'','-c':True,'-a':False,'weight':'','output':processDirectory + 'DropAlong20m.tif','GRASS_REGION_PARAMETER':None,'GRASS_REGION_CELLSIZE_PARAMETER':0,'GRASS_RASTER_FORMAT_OPT':'',
    'GRASS_RASTER_FORMAT_META':''})
    
#Combine the two and give greater weight to a steeper drop
processing.run("gdal:rastercalculator", {'INPUT_A': processDirectory + 'DropAlong5m.tif','BAND_A': 1,'INPUT_B': processDirectory + 'DropAlong20m.tif','BAND_B': 1,'INPUT_C': None,'BAND_C': -1,'INPUT_D': None,'BAND_D': -1,'INPUT_E': None,'BAND_E': -1,'INPUT_F': None,'BAND_F': -1,
    'FORMULA': 'A + ((B ** 1.5) * 0.08)','NO_DATA': None,'RTYPE': 5,'EXTRA': '','OPTIONS': compressOptions,'EXTENT_OPT': 0,'PROJWIN': None,'OUTPUT': processDirectory + 'CombinedDropFactor.tif'})

#Work out the score as a product of the size of the drop and the amount of water going over the drop
processing.run("gdal:rastercalculator", {'INPUT_A': processDirectory + 'FlowAccumulationPlusRain.tif','BAND_A': 1,'INPUT_B': processDirectory + 'CombinedDropFactor.tif','BAND_B': 1,'INPUT_C': None,'BAND_C': -1,'INPUT_D': None,'BAND_D': -1,'INPUT_E': None,'BAND_E': -1,'INPUT_F': None,'BAND_F': -1,
    'FORMULA': '(A ** 0.25) * B','NO_DATA': None,'RTYPE': 5,'EXTRA': '','OPTIONS': compressOptions,'EXTENT_OPT': 0,'PROJWIN': None,'OUTPUT': processDirectory + 'DropFactorPlusFlowAcc.tif'})

#Determine where the largest local score is
processing.run("grass7:r.neighbors", {'input':processDirectory + 'DropFactorPlusFlowAcc.tif','selection':processDirectory + 'DropFactorPlusFlowAcc.tif','method':4,'size':21,
    'gauss':None,'quantile':'','-c':True,'-a':False,'weight':'','output':processDirectory + 'DropFactorPlusFlowAccMaximum.tif','GRASS_REGION_PARAMETER':None,'GRASS_REGION_CELLSIZE_PARAMETER':0,
    'GRASS_RASTER_FORMAT_OPT':'','GRASS_RASTER_FORMAT_META':''})
    
#See if each pixel is the largest local drop
processing.run("gdal:rastercalculator", {'INPUT_A': processDirectory + 'DropFactorPlusFlowAcc.tif','BAND_A': 1,'INPUT_B': processDirectory + 'DropFactorPlusFlowAccMaximum.tif','BAND_B': 1,'INPUT_C': None,'BAND_C': -1,'INPUT_D': None,'BAND_D': -1,'INPUT_E': None,'BAND_E': -1,'INPUT_F': None,'BAND_F': -1,
    'FORMULA': 'A * (A == B)','NO_DATA':0,'RTYPE': 5,'EXTRA': '','OPTIONS': compressOptions,'EXTENT_OPT': 0,'PROJWIN': None,'OUTPUT': processDirectory + 'DropFactorPlusFlowAccBiggest.tif'})

#Convert these pixels to points
processing.run("native:pixelstopoints", {'INPUT_RASTER':processDirectory + 'DropFactorPlusFlowAccBiggest.tif','RASTER_BAND':1,'FIELD_NAME':'DropValue',
    'OUTPUT':processDirectory + 'BiggestDropPoints.gpkg'})
    
"""
##########################################################
Point processing
"""

#Only get the points that have a decent score
processing.run("native:extractbyattribute", {'INPUT':processDirectory + 'BiggestDropPoints.gpkg','FIELD':'DropValue','OPERATOR':2,'VALUE':'3000',
    'OUTPUT':processDirectory + 'BiggestDropPointsFilter.gpkg'})
    
#Add in the catchment values for reference
processing.run("native:rastersampling", {'INPUT':processDirectory + 'BiggestDropPointsFilter.gpkg',
    'RASTERCOPY':processDirectory + 'CombinedFlowAccumulation.tif','COLUMN_PREFIX':'Catchment','OUTPUT':processDirectory + 'BiggestDropPointsFilterPlusCatchment.gpkg'})
    
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
