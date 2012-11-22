"""
SuprimeCam-specific overrides for ProcessCcdTask
(applied after Subaru overrides in ../processCcd.py).
"""
from lsst.obs.subaru.isr import SuprimeCamIsrTask

root.isr.retarget(SuprimeCamIsrTask)  # custom task that adds guider correction
root.isr.doBias = False
root.isr.doDark = False
root.isr.doWrite = False

# crosstalk coefficients for SuprimeCam, as crudely measured by RHL

if False: # for RHL
    root.isr.crosstalkCoeffs.values = [
        0.00e+00, -8.93e-05, -1.11e-04, -1.18e-04,
        -8.09e-05,  0.00e+00, -7.15e-06, -1.12e-04,
        -9.90e-05, -2.28e-05,  0.00e+00, -9.64e-05,
        -9.59e-05, -9.85e-05, -8.77e-05,  0.00e+00,
        ]

# coefficients derived from Yagi+ 2012
root.isr.crosstalkCoeffs.crossTalkCoeffs1 = [
    0,   -0.000148, -0.000162, -0.000167,   # cAA,cAB,cAC,cAD
    -0.000148, 0, -0.000077, -0.000162,     # cBA,cBB,cBC,cBD
    -0.000162, -0.000077, 0, -0.000148,     # cCA,cCB,cCC,cCD
    -0.000167, -0.000162, -0.000148, 0,     # cDA,cDB,cDC,cDD 
    ]
root.isr.crosstalkCoeffs.crossTalkCoeffs2 = [
    0,       0.000051,0.000050,0.000053, 
    0.000051,0,       0,       0.000050, 
    0.000050,0,       0,       0.000051, 
    0.000053,0.000050,0.000051,0,
    ]
root.isr.crosstalkCoeffs.relativeGainsPreampAndSigboard = [
    0.949, 0.993, 0.976, 0.996,
    0.973, 0.984, 0.966, 0.977,
    1.008, 0.989, 0.970, 0.976,
    0.961, 0.966, 1.008, 0.967,
    0.967, 0.984, 0.998, 1.000,
    0.989, 1.000, 1.034, 1.030,
    0.957, 1.019, 0.952, 0.979,
    0.974, 1.015, 0.967, 0.962,
    0.972, 0.932, 0.999, 0.963,
    0.987, 0.985, 0.986, 1.012,
    ]

# nonlinearity for SuprimeCam
root.isr.linearizationCoefficient = 2.5e-7

# color terms
from lsst.meas.photocal.colorterms import Colorterm
from lsst.obs.suprimecam.colorterms import colortermsData
Colorterm.setColorterms(colortermsData)
Colorterm.setActiveDevice("Hamamatsu")
