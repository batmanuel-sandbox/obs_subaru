#
# LSST Data Management System
# Copyright 2008-2013 LSST Corporation.
#
# This product includes software developed by the
# LSST Project (http://www.lsst.org/).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the LSST License Statement and
# the GNU General Public License along with this program.  If not,
# see <http://www.lsstcorp.org/LegalNotices/>.
#
import math
import numpy

import lsst.pex.config as pexConf
import lsst.afw.table as afwTable
import lsst.pipe.base as pipeBase
import lsst.afw.math as afwMath
import lsst.afw.geom as afwGeom
import lsst.afw.image as afwImage
import lsst.afw.detection as afwDet

__all__ = 'SourceDeblendConfig', 'SourceDeblendTask'

class SourceDeblendConfig(pexConf.Config):

    edgeHandling = pexConf.ChoiceField(
        doc='What to do when a peak to be deblended is close to the edge of the image',
        dtype=str, default='ramp',
        allowed = {
            'clip': 'Clip the template at the edge AND the mirror of the edge.',
            'ramp': 'Ramp down flux at the image edge by the PSF',
            'noclip': 'Ignore the edge when building the symmetric template.',
            })
    
    strayFluxToPointSources = pexConf.ChoiceField(
        doc='When the deblender should attribute stray flux to point sources',
        dtype=str, default='necessary',
        allowed = {
            'necessary': 'When there is not an extended object in the footprint',
            'always': 'Always',
            'never': 'Never; stray flux will not be attributed to any deblended child if the deblender thinks all peaks look like point sources',
            }
            )

    findStrayFlux = pexConf.Field(dtype=bool, default=True,
                                  doc='Find stray flux---flux not claimed by any child in the deblender.')

    assignStrayFlux = pexConf.Field(dtype=bool, default=True,
                                    doc='Assign stray flux to deblend children.  Implies findStrayFlux.')

    clipStrayFluxFraction = pexConf.Field(dtype=float, default=0.001,
                                          doc=('When splitting stray flux, clip fractions below this value to zero.'))
    
    psfChisq1 = pexConf.Field(dtype=float, default=1.5, optional=False,
                                doc=('Chi-squared per DOF cut for deciding a source is '+
                                     'a PSF during deblending (un-shifted PSF model)'))
    psfChisq2 = pexConf.Field(dtype=float, default=1.5, optional=False,
                                doc=('Chi-squared per DOF cut for deciding a source is '+
                                     'PSF during deblending (shifted PSF model)'))
    psfChisq2b = pexConf.Field(dtype=float, default=1.5, optional=False,
                                doc=('Chi-squared per DOF cut for deciding a source is '+
                                     'a PSF during deblending (shifted PSF model #2)'))
    maxNumberOfPeaks = pexConf.Field(dtype=int, default=0,
                                     doc=("Only deblend the brightest maxNumberOfPeaks peaks in the parent" +
                                          " (<= 0: unlimited)"))

    tinyFootprintSize = pexConf.Field(dtype=int, default=2,
                                      doc=('Footprints smaller in width or height than this value will be ignored; 0 to never ignore.'))
    
class SourceDeblendTask(pipeBase.Task):
    """Split blended sources into individual sources.

    This task has no return value; it only modifies the SourceCatalog in-place.
    """
    ConfigClass = SourceDeblendConfig
    _DefaultName = "sourceDeblend"

    def __init__(self, schema, **kwargs):
        """Create the task, adding necessary fields to the given schema.

        @param[in,out] schema        Schema object for measurement fields; will be modified in-place.
        @param         **kwds        Passed to Task.__init__.
        """
        pipeBase.Task.__init__(self, **kwargs)

        self.nChildKey = schema.addField('deblend.nchild', type=int,
                                         doc='Number of children this object has (defaults to 0)')
        self.psfKey = schema.addField('deblend.deblended-as-psf', type='Flag',
                                      doc='Deblender thought this source looked like a PSF')
        self.psfCenterKey = schema.addField('deblend.psf-center', type='PointD',
                                         doc='If deblended-as-psf, the PSF centroid')
        self.psfFluxKey = schema.addField('deblend.psf-flux', type='D',
                                           doc='If deblended-as-psf, the PSF flux')
        self.tooManyPeaksKey = schema.addField('deblend.too-many-peaks', type='Flag',
                                               doc='Source had too many peaks; ' +
                                               'only the brightest were included')
        self.deblendFailedKey = schema.addField('deblend.failed', type='Flag',
                                                doc="Deblending failed on source")

        self.deblendSkippedKey = schema.addField('deblend.skipped', type='Flag',
                                                doc="Deblender skipped this source")

        self.deblendRampedTemplateKey = schema.addField(
            'deblend.ramped_template', type='Flag',
            doc=('This source was near an image edge and the deblender used ' +
                 '"ramp" edge-handling.'))

        self.deblendPatchedTemplateKey = schema.addField(
            'deblend.patched_template', type='Flag',
            doc=('This source was near an image edge and the deblender used ' +
                 '"patched" edge-handling.'))

        self.hasStrayFluxKey = schema.addField(
            'deblend.has_stray_flux', type='Flag',
            doc=('This source was assigned some stray flux'))
        
        self.log.logdebug('Added keys to schema: %s' % ", ".join(str(x) for x in (
                    self.nChildKey, self.psfKey, self.psfCenterKey, self.psfFluxKey, self.tooManyPeaksKey)))

    @pipeBase.timeMethod
    def run(self, exposure, sources, psf):
        """Run deblend().

        @param[in]     exposure Exposure to process
        @param[in,out] sources  SourceCatalog containing sources detected on this exposure.
        @param[in]     psf      PSF

        @return None
        """
        self.deblend(exposure, sources, psf)

    def _getPsfFwhm(self, psf, bbox):
        # It should be easier to get a PSF's fwhm;
        # https://dev.lsstcorp.org/trac/ticket/3030
        return psf.computeShape().getDeterminantRadius() * 2.35
        
    @pipeBase.timeMethod
    def deblend(self, exposure, srcs, psf):
        """Deblend.
        
        @param[in]     exposure Exposure to process
        @param[in,out] srcs     SourceCatalog containing sources detected on this exposure.
        @param[in]     psf      PSF
                       
        @return None
        """
        self.log.info("Deblending %d sources" % len(srcs))

        from lsst.meas.deblender.baseline import deblend
        import lsst.meas.algorithms as measAlg

        # find the median stdev in the image...
        mi = exposure.getMaskedImage()
        stats = afwMath.makeStatistics(mi.getVariance(), mi.getMask(), afwMath.MEDIAN)
        sigma1 = math.sqrt(stats.getValue(afwMath.MEDIAN))

        schema = srcs.getSchema()

        n0 = len(srcs)
        nparents = 0
        for i,src in enumerate(srcs):
            fp = src.getFootprint()
            pks = fp.getPeaks()
            if len(pks) < 2:
                continue
            nparents += 1
            bb = fp.getBBox()
            psf_fwhm = self._getPsfFwhm(psf, bb)

            self.log.logdebug('Parent %i: deblending %i peaks' % (int(src.getId()), len(pks)))

            self.preSingleDeblendHook(exposure, srcs, i, fp, psf, psf_fwhm, sigma1)
            npre = len(srcs)

            # This should really be set in deblend, but deblend doesn't have access to the src
            src.set(self.tooManyPeaksKey, len(fp.getPeaks()) > self.config.maxNumberOfPeaks)

            try:
                res = deblend(
                    fp, mi, psf, psf_fwhm, sigma1=sigma1,
                    psfChisqCut1 = self.config.psfChisq1,
                    psfChisqCut2 = self.config.psfChisq2,
                    psfChisqCut2b= self.config.psfChisq2b,
                    maxNumberOfPeaks=self.config.maxNumberOfPeaks,
                    strayFluxToPointSources=self.config.strayFluxToPointSources,
                    assignStrayFlux=self.config.assignStrayFlux,
                    findStrayFlux=(self.config.assignStrayFlux or
                                   self.config.findStrayFlux),
                    rampFluxAtEdge=(self.config.edgeHandling == 'ramp'),
                    patchEdges=(self.config.edgeHandling == 'noclip'),
                    tinyFootprintSize=self.config.tinyFootprintSize,
                    clipStrayFluxFraction=self.config.clipStrayFluxFraction,
                    )
                src.set(self.deblendFailedKey, False)
            except Exception as e:
                self.log.warn("Error deblending source %d: %s" % (src.getId(), e))
                src.set(self.deblendFailedKey, True)
                import traceback
                traceback.print_exc()
                continue

            kids = []
            nchild = 0
            for j,peak in enumerate(res.peaks):
                if peak.skip:
                    # skip this source?
                    self.log.logdebug('Skipping out-of-bounds peak at (%i,%i)' %
                                      (pks[j].getIx(), pks[j].getIy()))
                    src.set(self.deblendSkippedKey, True)
                    continue

                heavy = peak.getFluxPortion()
                if heavy is None:
                    # This can happen for children >= maxNumberOfPeaks
                    self.log.logdebug('Skipping peak at (%i,%i), child %i of %i: no flux portion'
                                      % (pks[j].getIx(), pks[j].getIy(), j+1, len(res.peaks)))
                    src.set(self.deblendSkippedKey, True)
                    continue

                src.set(self.deblendSkippedKey, False)

                child = srcs.addNew(); nchild += 1
                child.setParent(src.getId())
                child.setFootprint(heavy)
                child.set(self.psfKey, peak.deblendedAsPsf)
                child.set(self.hasStrayFluxKey, peak.strayFlux is not None)
                if peak.deblendedAsPsf:
                    (cx,cy) = peak.psfFitCenter
                    child.set(self.psfCenterKey, afwGeom.Point2D(cx, cy))
                    child.set(self.psfFluxKey, peak.psfFitFlux)
                child.set(self.deblendRampedTemplateKey, peak.hasRampedTemplate)
                child.set(self.deblendPatchedTemplateKey, peak.patched)
                kids.append(child)

            src.set(self.nChildKey, nchild)
            
            self.postSingleDeblendHook(exposure, srcs, i, npre, kids, fp, psf, psf_fwhm, sigma1, res)

        n1 = len(srcs)
        self.log.info('Deblended: of %i sources, %i were deblended, creating %i children, total %i sources' %
                      (n0, nparents, n1-n0, n1))

    def preSingleDeblendHook(self, exposure, srcs, i, fp, psf, psf_fwhm, sigma1):
        pass
    
    def postSingleDeblendHook(self, exposure, srcs, i, npre, kids, fp, psf, psf_fwhm, sigma1, res):
        pass
