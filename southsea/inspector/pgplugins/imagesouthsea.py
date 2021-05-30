# -*- coding: utf-8 -*-

# This file is part of Argos.
#
# Argos is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Argos is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Argos. If not, see <http://www.gnu.org/licenses/>.

""" PyQtGraph 2D image plot
"""
from __future__ import division, print_function

import os
import logging, math
from pprint import pprint

import numpy as np
import pyqtgraph as pg

from functools import partial
from collections import OrderedDict

from argos.info import DEBUGGING
from argos.config.boolcti import BoolCti, BoolGroupCti
from argos.config.choicecti import ChoiceCti
from argos.config.groupcti import MainGroupCti
from argos.inspector.abstract import AbstractInspector, InvalidDataError, UpdateReason
from argos.inspector.pgplugins.colorbar import ArgosColorLegendItem
from argos.inspector.pgplugins.pgctis import (
    X_AXIS, Y_AXIS, BOTH_AXES, NO_LABEL_STR, defaultAutoRangeMethods, PgAxisLabelCti,
    PgAxisCti, PgAxisFlipCti, PgAspectRatioCti, PgAxisRangeCti, PgGridCti,
    PgColorMapCti, PgColorLegendCti, PgColorLegendLabelCti, PgShowHistCti,
    PgShowDragLinesCti, setXYAxesAutoRangeOn, PgPlotDataItemCti)
from argos.inspector.pgplugins.pgplotitem import ArgosPgPlotItem
from argos.qt import Qt, QtCore, QtGui, QtSlot

from argos.utils.cls import array_has_real_numbers, check_class, is_an_array, to_string
from argos.utils.cls import array_kind_label
from argos.utils.defs import RIGHT_ARROW
from argos.utils.masks import (ArrayWithMask, replaceMaskedValueWithFloat,
                               nanPercentileOfSubsampledArrayWithMask)

from objbrowser import browse

logger = logging.getLogger(__name__)

ROW_TITLE, COL_TITLE = 0, 0  # colspan = 3
ROW_COLOR, COL_COLOR = 1, 2  # rowspan = 2
ROW_HOR_LINE, COL_HOR_LINE = 1, 0
ROW_IMAGE, COL_IMAGE = 2, 0
ROW_VER_LINE, COL_VER_LINE = 2, 1
ROW_PROBE, COL_PROBE = 3, 0  # colspan = 2


def calc_pg_image_plot2d_data_range(pgImagePlot2d, percentage, crossPlot, subsample):
    """ Calculates the range from the inspectors' sliced array. Discards percentage of the minimum
        and percentage of the maximum values of the inspector.slicedArray

        :param pgImagePlot2d: the range methods will work on (the sliced array) of this inspector.
        :param float percentage: percentage that will be discarded.
        :param bool crossPlot: if None, the range will be calculated from the entire sliced array,
            if "horizontal" or "vertical" the range will be calculated from the data under the
            horizontal or vertical cross hairs.
            If the cursor is outside the image, there is no valid data under the cross-hair and
            the range will be determined from the sliced array as a fall back.
        :param bool subsample: if True, the image will be subsampled (to 200 by 200) before
            calculating the range. This to improve performance by large images.
    """
    check_class(pgImagePlot2d.slicedArray, ArrayWithMask)  # sanity check

    if crossPlot is None:
        array = pgImagePlot2d.slicedArray  # the whole image

    elif crossPlot == 'horizontal':
        if pgImagePlot2d.crossPlotRow is not None:
            array = pgImagePlot2d.slicedArray[pgImagePlot2d.crossPlotRow, :]
        else:
            array = pgImagePlot2d.slicedArray  # fall back on complete sliced array

    elif crossPlot == 'vertical':
        if pgImagePlot2d.crossPlotCol is not None:
            array = pgImagePlot2d.slicedArray[:, pgImagePlot2d.crossPlotCol]
        else:
            array = pgImagePlot2d.slicedArray  # fall back on complete sliced array
    else:
        raise ValueError("crossPlot must be: None, 'horizontal' or 'vertical', got: {}"
                         .format(crossPlot))

    return nanPercentileOfSubsampledArrayWithMask(array, (percentage, 100 - percentage), subsample)


def cross_plot_auto_range_methods(pgImagePlot2d, crossPlot, intialItems=None):
    """ Creates an ordered dict with autorange methods for an PgImagePlot2d inspector.

        :param pgImagePlot2d: the range methods will work on (the sliced array) of this inspector.
        :param crossPlot: if None, the range will be calculated from the entire sliced array,
            if "horizontal" or "vertical" the range will be calculated from the data under the
            horizontal or vertical cross hairs
        :param intialItems: will be passed on to the  OrderedDict constructor.
    """
    rangeFunctions = OrderedDict({} if intialItems is None else intialItems)

    # If crossPlot is "horizontal" or "vertical" make functions that determine the range from the
    # data at the cross hair.
    if crossPlot:
        rangeFunctions['cross all data'] = partial(calc_pg_image_plot2d_data_range, pgImagePlot2d,
                                                   0.0, crossPlot)
        for percentage in [0.1, 0.2, 0.5, 1, 2, 5, 10, 20]:
            label = "cross discard {}%".format(percentage)
            rangeFunctions[label] = partial(calc_pg_image_plot2d_data_range, pgImagePlot2d,
                                            percentage, crossPlot)

    # Always add functions that determine the data from the complete sliced array.
    for percentage in [0.1, 0.2, 0.5, 1, 2, 5, 10, 20]:
        rangeFunctions['image all data'] = partial(calc_pg_image_plot2d_data_range, pgImagePlot2d,
                                                   0.0, None)

        label = "image discard {}%".format(percentage)
        rangeFunctions[label] = partial(calc_pg_image_plot2d_data_range, pgImagePlot2d,
                                        percentage, None)
    return rangeFunctions


class PgImageSouthSeaCti(MainGroupCti):
    """ Configuration tree item for a PgImageSouthSeaCti inspector
    """

    def __init__(self, pgImageSouthSea, nodeName):
        """ Constructor

            Maintains a link to the target pgImagePlot2d inspector, so that changes in the
            configuration can be applied to the target by simply calling the apply method.
            Vice versa, it can connect signals to the target.
        """
        super(PgImageSouthSeaCti, self).__init__(nodeName)
        check_class(pgImageSouthSea, PgImageSouthSea)
        self.pgImageSouthSea = pgImageSouthSea
        imagePlotItem = self.pgImageSouthSea.imagePlotItem
        viewBox = imagePlotItem.getViewBox()

        self.insertChild(
            ChoiceCti('title', 0, editable=True,
                      configValues=["{base-name} -- {name} {slices}",
                                    "{name} {slices}", "{path} {slices}"]))

        #### Axes ####

        self.aspectLockedCti = self.insertChild(PgAspectRatioCti(viewBox))

        self.xAxisCti = self.insertChild(PgAxisCti('x-axis'))
        self.xAxisCti.insertChild(
            PgAxisLabelCti(imagePlotItem, 'bottom', self.pgImageSouthSea.collector,
                           defaultData=1,
                           configValues=[NO_LABEL_STR, "{x-dim} [index]"]))
        self.xFlippedCti = self.xAxisCti.insertChild(PgAxisFlipCti(viewBox, X_AXIS))
        self.xAxisRangeCti = self.xAxisCti.insertChild(PgAxisRangeCti(viewBox, X_AXIS))

        self.yAxisCti = self.insertChild(PgAxisCti('y-axis'))
        self.yAxisCti.insertChild(
            PgAxisLabelCti(imagePlotItem, 'left', self.pgImageSouthSea.collector,
                           defaultData=1,
                           configValues=[NO_LABEL_STR, "{y-dim} [index]"]))
        self.yFlippedCti = self.yAxisCti.insertChild(
            PgAxisFlipCti(viewBox, Y_AXIS, defaultData=True))
        self.yAxisRangeCti = self.yAxisCti.insertChild(PgAxisRangeCti(viewBox, Y_AXIS))

        #### Color scale ####

        self.colorCti = self.insertChild(PgAxisCti('color scale'))

        self.colorCti.insertChild(PgColorLegendLabelCti(
            pgImageSouthSea.colorLegendItem, self.pgImageSouthSea.collector, defaultData=1,
            configValues=[NO_LABEL_STR, "{name} {unit}", "{path} {unit}",
                          "{name}", "{path}", "{raw-unit}"]))

        self.colorCti.insertChild(PgColorMapCti(self.pgImageSouthSea.colorLegendItem))

        self.showHistCti = self.colorCti.insertChild(
            PgShowHistCti(pgImageSouthSea.colorLegendItem))
        self.showDragLinesCti = self.colorCti.insertChild(
            PgShowDragLinesCti(pgImageSouthSea.colorLegendItem))

        colorAutoRangeFunctions = defaultAutoRangeMethods(self.pgImageSouthSea)
        self.colorLegendCti = self.colorCti.insertChild(
            PgColorLegendCti(pgImageSouthSea.colorLegendItem, colorAutoRangeFunctions,
                             nodeName="range"))

        # If True, the image is automatically downsampled to match the screen resolution. This
        # improves performance for large images and reduces aliasing. If autoDownsample is not
        # specified, then ImageItem will choose whether to downsample the image based on its size.
        self.autoDownSampleCti = self.insertChild(BoolCti('auto down sample', True))
        self.zoomModeCti = self.insertChild(BoolCti('rectangle zoom mode', False))

        ### Probe and cross-hair plots ###

        self.probeCti = self.insertChild(BoolCti('show probe', True))
        self.crossPlotGroupCti = self.insertChild(BoolGroupCti('cross-hair', expanded=False))
        self.crossPenCti = self.crossPlotGroupCti.insertChild(PgPlotDataItemCti(expanded=False))

        self.horCrossPlotCti = self.crossPlotGroupCti.insertChild(
            BoolCti('horizontal', False, expanded=False))

        self.horCrossPlotCti.insertChild(PgGridCti(pgImageSouthSea.horCrossPlotItem))
        self.horCrossPlotRangeCti = self.horCrossPlotCti.insertChild(
            PgAxisRangeCti(
                self.pgImageSouthSea.horCrossPlotItem.getViewBox(), Y_AXIS, nodeName="data range",
                autoRangeFunctions=cross_plot_auto_range_methods(self.pgImageSouthSea, "horizontal")))

        self.verCrossPlotCti = self.crossPlotGroupCti.insertChild(
            BoolCti('vertical', False, expanded=False))
        self.verCrossPlotCti.insertChild(PgGridCti(pgImageSouthSea.verCrossPlotItem))
        self.verCrossPlotRangeCti = self.verCrossPlotCti.insertChild(
            PgAxisRangeCti(
                self.pgImageSouthSea.verCrossPlotItem.getViewBox(), X_AXIS, nodeName="data range",
                autoRangeFunctions=cross_plot_auto_range_methods(self.pgImageSouthSea, "vertical")))

        # Connect signals.

        # Use a queued connect to schedule the reset after current events have been processed.
        self.pgImageSouthSea.colorLegendItem.sigResetColorScale.connect(
            self.colorLegendCti.setAutoRangeOn, type=Qt.QueuedConnection)
        self.pgImageSouthSea.imagePlotItem.sigResetAxis.connect(
            self.setImagePlotAutoRangeOn, type=Qt.QueuedConnection)
        self.pgImageSouthSea.horCrossPlotItem.sigResetAxis.connect(
            self.setHorCrossPlotAutoRangeOn, type=Qt.QueuedConnection)
        self.pgImageSouthSea.verCrossPlotItem.sigResetAxis.connect(
            self.setVerCrossPlotAutoRangeOn, type=Qt.QueuedConnection)

        # Also update axis auto range tree items when linked axes are resized
        horCrossViewBox = self.pgImageSouthSea.horCrossPlotItem.getViewBox()
        horCrossViewBox.sigRangeChangedManually.connect(self.xAxisRangeCti.setAutoRangeOff)
        verCrossViewBox = self.pgImageSouthSea.verCrossPlotItem.getViewBox()
        verCrossViewBox.sigRangeChangedManually.connect(self.yAxisRangeCti.setAutoRangeOff)

    def _closeResources(self):
        """ Disconnects signals.
            Is called by self.finalize when the cti is deleted.
        """
        self.pgImageSouthSea.colorLegendItem.sigResetColorScale.disconnect(
            self.colorLegendCti.setAutoRangeOn)

        verCrossViewBox = self.pgImageSouthSea.verCrossPlotItem.getViewBox()
        verCrossViewBox.sigRangeChangedManually.disconnect(self.yAxisRangeCti.setAutoRangeOff)
        horCrossViewBox = self.pgImageSouthSea.horCrossPlotItem.getViewBox()
        horCrossViewBox.sigRangeChangedManually.disconnect(self.xAxisRangeCti.setAutoRangeOff)

        self.pgImageSouthSea.verCrossPlotItem.sigResetAxis.disconnect(self.setVerCrossPlotAutoRangeOn)
        self.pgImageSouthSea.horCrossPlotItem.sigResetAxis.disconnect(self.setHorCrossPlotAutoRangeOn)
        self.pgImageSouthSea.imagePlotItem.sigResetAxis.disconnect(self.setImagePlotAutoRangeOn)

    def setImagePlotAutoRangeOn(self, axisNumber):
        """ Sets the image plot's auto-range on for the axis with number axisNumber.

            :param axisNumber: 0 (X-axis), 1 (Y-axis), 2, (Both X and Y axes).
        """
        setXYAxesAutoRangeOn(self, self.xAxisRangeCti, self.yAxisRangeCti, axisNumber)

    def setHorCrossPlotAutoRangeOn(self, axisNumber):
        """ Sets the horizontal cross-hair plot's auto-range on for the axis with number axisNumber.

            :param axisNumber: 0 (X-axis), 1 (Y-axis), 2, (Both X and Y axes).
        """
        setXYAxesAutoRangeOn(self, self.xAxisRangeCti, self.horCrossPlotRangeCti, axisNumber)

    def setVerCrossPlotAutoRangeOn(self, axisNumber):
        """ Sets the vertical cross-hair plot's auto-range on for the axis with number axisNumber.

            :param axisNumber: 0 (X-axis), 1 (Y-axis), 2, (Both X and Y axes).
        """
        setXYAxesAutoRangeOn(self, self.verCrossPlotRangeCti, self.yAxisRangeCti, axisNumber)

    def resetRangesToDefault(self):
        """ Resets range settings to the default data.
        """
        self.xAxisRangeCti.autoRangeCti.data = True
        self.yAxisRangeCti.autoRangeCti.data = True
        self.colorLegendCti.autoRangeCti.data = True
        self.horCrossPlotRangeCti.autoRangeCti.data = True
        self.verCrossPlotRangeCti.autoRangeCti.data = True


class PgImageSouthSea(AbstractInspector):
    """ Draws an image plot of a two-dimensional array (slice).

        Plotting is done with the PyQtGraph package. See www.pyqtgraph.org.
    """

    def __init__(self, collector, parent=None):
        """ Constructor. See AbstractInspector constructor for parameters.
        """
        super(PgImageSouthSea, self).__init__(collector, parent=parent)

        # The sliced array is kept in memory. This may be different per inspector, e.g. 3D
        # inspectors may decide that this uses to much memory. The slice is therefor not stored
        # in the collector.
        self.slicedArray = None

        self.titleLabel = pg.LabelItem('title goes here...')

        # The image item
        self.imagePlotItem = ArgosPgPlotItem()
        self.viewBox = self.imagePlotItem.getViewBox()
        print("I like ", np.pi)
        self.viewBox.disableAutoRange(BOTH_AXES)
        pprint(self.viewBox.background)

        self.imageItem = pg.ImageItem()
        self.imageItem.setPos(-0.5, -0.5)  # Center on pixels (see pg.ImageView.setImage source code)
        self.imagePlotItem.addItem(self.imageItem)

        self.colorLegendItem = ArgosColorLegendItem(self.imageItem)

        # Probe and cross hair plots
        self.crossPlotRow = None  # the row coordinate of the cross hair. None if no cross hair.
        self.crossPlotCol = None  # the col coordinate of the cross hair. None if no cross hair.
        self.horCrossPlotItem = ArgosPgPlotItem()
        self.verCrossPlotItem = ArgosPgPlotItem()
        self.horCrossPlotItem.setXLink(self.imagePlotItem)
        self.verCrossPlotItem.setYLink(self.imagePlotItem)
        self.horCrossPlotItem.setLabel('left', ' ')
        self.verCrossPlotItem.setLabel('bottom', ' ')
        self.horCrossPlotItem.showAxis('top', True)
        self.horCrossPlotItem.showAxis('bottom', False)
        self.verCrossPlotItem.showAxis('right', True)
        self.verCrossPlotItem.showAxis('left', False)

        self.crossPen = pg.mkPen("#BFBFBF")
        self.crossShadowPen = pg.mkPen([0, 0, 0, 100], width=3)
        self.crossLineHorShadow = pg.InfiniteLine(angle=0, movable=False, pen=self.crossShadowPen)
        self.crossLineVerShadow = pg.InfiniteLine(angle=90, movable=False, pen=self.crossShadowPen)
        self.crossLineHorizontal = pg.InfiniteLine(angle=0, movable=False, pen=self.crossPen)
        self.crossLineVertical = pg.InfiniteLine(angle=90, movable=False, pen=self.crossPen)

        # no change?
        # self.imagePlotItem.addItem(self.crossLineVerShadow, ignoreBounds=True)
        # self.imagePlotItem.addItem(self.crossLineHorShadow, ignoreBounds=True)
        # self.imagePlotItem.addItem(self.crossLineVertical, ignoreBounds=True)
        # self.imagePlotItem.addItem(self.crossLineHorizontal, ignoreBounds=True)

        self.probeLabel = pg.LabelItem('xxxx', justify='left')

        # Layout

        # Hiding the horCrossPlotItem and horCrossPlotItem will still leave some space in the
        # grid layout. We therefore remove them from the layout instead. We need to know if they
        # are already added.
        self.horPlotAdded = False
        self.verPlotAdded = False

        self.graphicsLayoutWidget = pg.GraphicsLayoutWidget()
        self.contentsLayout.addWidget(self.graphicsLayoutWidget)

        self.graphicsLayoutWidget.addItem(self.titleLabel, ROW_TITLE, COL_TITLE, colspan=3)
        self.graphicsLayoutWidget.addItem(self.colorLegendItem, ROW_COLOR, COL_COLOR, rowspan=2)
        self.graphicsLayoutWidget.addItem(self.imagePlotItem, ROW_IMAGE, COL_IMAGE)
        self.graphicsLayoutWidget.addItem(self.probeLabel, ROW_PROBE, COL_PROBE, colspan=3)

        gridLayout = self.graphicsLayoutWidget.ci.layout  # A QGraphicsGridLayout
        gridLayout.setHorizontalSpacing(10)
        gridLayout.setVerticalSpacing(10)
        # gridLayout.setRowSpacing(ROW_PROBE, 40)

        gridLayout.setRowStretchFactor(ROW_HOR_LINE, 1)
        gridLayout.setRowStretchFactor(ROW_IMAGE, 2)
        gridLayout.setColumnStretchFactor(COL_IMAGE, 2)
        gridLayout.setColumnStretchFactor(COL_VER_LINE, 1)

        # Configuration tree
        self._config = PgImageSouthSeaCti(pgImageSouthSea=self, nodeName='2D image plot')

        # Connect signals
        # Based mouseMoved on crosshair.py from the PyQtGraph examples directory.
        # I did not use the SignalProxy because I did not see any difference.
        self.imagePlotItem.scene().sigMouseMoved.connect(self.mouseMoved)
        # self.imagePlotItem.scene()..connect(self.mouseMoved)
        # browse(locals())

    def finalize(self):
        """ Is called before destruction. Can be used to clean-up resources.
        """
        logger.debug("Finalizing: {}".format(self))
        self.colorLegendItem.finalize()
        self.imagePlotItem.scene().sigMouseMoved.disconnect(self.mouseMoved)
        self.imagePlotItem.close()
        self.graphicsLayoutWidget.close()

    @classmethod
    def axesNames(cls):
        """ The names of the axes that this inspector visualizes.
            See the parent class documentation for a more detailed explanation.
        """
        return tuple(['Y', 'X'])

    def _clearContents(self):
        """ Clears the contents when no valid data is available
        """
        logger.debug("Clearing inspector contents")
        self.slicedArray = None
        self.titleLabel.setText('')

        # Don't clear the imagePlotItem, the imageItem is only added in the constructor.
        self.imageItem.clear()
        if hasattr(self.imageItem, '_wasIntegerData'):
            del self.imageItem._wasIntegerData

        # Unfortunately PyQtGraph doesn't emit this signal when the image is cleared.
        self.imageItem.sigImageChanged.emit()

        self.imagePlotItem.setLabel('left', '')
        self.imagePlotItem.setLabel('bottom', '')
        self.colorLegendItem.setLabel('')
        # Set the histogram range and levels to finite values to prevent futher errors if this
        # function was called after an exception in self.drawContents
        # self.histLutItem.setHistogramRange(0, 100)
        # self.histLutItem.setLevels(0, 100)

        self.crossPlotRow, self.crossPlotCol = None, None

        self.probeLabel.setText('')
        self.crossLineHorizontal.setVisible(False)
        self.crossLineVertical.setVisible(False)
        self.crossLineHorShadow.setVisible(False)
        self.crossLineVerShadow.setVisible(False)

        self.horCrossPlotItem.clear()
        self.verCrossPlotItem.clear()

    def _drawContents(self, reason=None, initiator=None):
        """ Draws the plot contents from the sliced array of the collected repo tree item.

            The reason parameter is used to determine if the axes will be reset (the initiator
            parameter is ignored). See AbstractInspector.updateContents for their description.
        """

        # If auto-reset is true, reset config complete or partially, depending on the mode.
        if self._resetRequired(reason, initiator):
            self.resetConfig()

        self.crossPlotRow = None  # reset because the sliced array shape may change
        self.crossPlotCol = None  # idem dito

        gridLayout = self.graphicsLayoutWidget.ci.layout  # A QGraphicsGridLayout

        if self.config.horCrossPlotCti.configValue:
            gridLayout.setRowStretchFactor(ROW_HOR_LINE, 1)
            if not self.horPlotAdded:
                self.graphicsLayoutWidget.addItem(self.horCrossPlotItem, ROW_HOR_LINE, COL_HOR_LINE)
                self.horPlotAdded = True
                gridLayout.activate()
        else:
            gridLayout.setRowStretchFactor(ROW_HOR_LINE, 0)
            if self.horPlotAdded:
                self.graphicsLayoutWidget.removeItem(self.horCrossPlotItem)
                self.horPlotAdded = False
                gridLayout.activate()

        if self.config.verCrossPlotCti.configValue:
            gridLayout.setColumnStretchFactor(COL_VER_LINE, 1)
            if not self.verPlotAdded:
                self.graphicsLayoutWidget.addItem(self.verCrossPlotItem, ROW_VER_LINE, COL_VER_LINE)
                self.verPlotAdded = True
                gridLayout.activate()
        else:
            gridLayout.setColumnStretchFactor(COL_VER_LINE, 0)
            if self.verPlotAdded:
                self.graphicsLayoutWidget.removeItem(self.verCrossPlotItem)
                self.verPlotAdded = False
                gridLayout.activate()

        slicedArray = self.collector.getSlicedArray()
        if slicedArray is None:
            self._clearContents()
            raise InvalidDataError()  # Don't show message, to common.
        elif not array_has_real_numbers(slicedArray.data):
            self._clearContents()
            raise InvalidDataError(
                "Selected item contains {} data.".format(array_kind_label(slicedArray.data)))
        else:
            self.slicedArray = slicedArray

        # -- Valid plot data from here on --

        if self.config.crossPlotGroupCti.checkState != Qt.Unchecked:
            tempPlotDataItem = self.config.crossPenCti.createPlotDataItem()
            if tempPlotDataItem.opts['pen'] is None and tempPlotDataItem.opts['symbol'] is None:
                self.sigShowMessage.emit(
                    "The cross-hair pen 'line' and 'symbol' config options are both unchecked!")

        numElem = np.prod(self.slicedArray.data.shape)
        if numElem == 0:
            self.sigShowMessage.emit("Current slice is empty.")  # Not expected to happen.
        elif numElem == 1:
            self.sigShowMessage.emit("Current slice contains only a single data point.")

        # PyQtGraph doesn't handle masked arrays so we convert the masked values to Nans. Missing
        # data values are replaced by NaNs. The PyQtGraph image plot shows this as the color at the
        # lowest end of the color scale. Unfortunately we cannot choose a missing-value color, but
        # at least the Nans do not influence for the histogram and color range.
        # We don't update self.slicedArray here because the data probe should still be able to
        # print the actual value.
        imageArray = replaceMaskedValueWithFloat(self.slicedArray.data, self.slicedArray.mask,
                                                 np.nan, copyOnReplace=True)

        # Replace infinite value with Nans because PyQtGraph fails on them. Note that the CTIs of
        # the cross plots (e.g. horCrossPlotRangeCti) are still connected to self.slicedArray, so
        # if the cross section consists of only infs, they may not able to update the autorange.
        # A warning is issued in that case.
        # We don't update self.slicedArray here because the data probe should still be able to
        # print the actual value.
        imageArray = replaceMaskedValueWithFloat(imageArray, np.isinf(self.slicedArray.data),
                                                 np.nan, copyOnReplace=True)

        # PyQtGraph uses the following dimension order: T, X, Y, Color.
        # We need to transpose the slicedArray ourselves because axes = {'x':1, 'y':0}
        # doesn't seem to do anything.
        imageArray = imageArray.transpose()

        # Set the _wasIntegerData to True if the original data type was a signed or unsigned. This
        # allows the ArgosColorLegendItem to make histogram bins as if it were an integer
        self.imageItem._wasIntegerData = self.slicedArray.data.dtype.kind in 'ui'
        self.imageItem.setAutoDownsample(self.config.autoDownSampleCti.configValue)
        self.imageItem.setImage(imageArray, autoLevels=False)  # Do after _wasIntegerData is set!

        self.imagePlotItem.setRectangleZoomOn(self.config.zoomModeCti.configValue)

        # Always use pan mode in the cross plots. Rectangle zoom is akward there and it's nice to
        # still be able to pan.
        # self.horCrossPlotItem.setRectangleZoomOn(self.config.zoomModeCti.configValue)
        # self.verCrossPlotItem.setRectangleZoomOn(self.config.zoomModeCti.configValue)

        self.horCrossPlotItem.invertX(self.config.xFlippedCti.configValue)
        self.verCrossPlotItem.invertY(self.config.yFlippedCti.configValue)

        self.probeLabel.setVisible(self.config.probeCti.configValue)

        self.titleLabel.setText(self.configValue('title').format(**self.collector.rtiInfo))

        logger.debug("Show Data log with logBranch()")
        self.config.logBranch()
        self.config.updateTarget()

    @QtSlot(object)
    def mouseMoved(self, viewPos):
        """ Updates the probe text with the values under the cursor.
            Draws a vertical line and a symbol at the position of the probe.
        """
        try:
            check_class(viewPos, QtCore.QPointF)
            show_data_point = False  # shows the data point as a circle in the cross hair plots
            self.crossPlotRow, self.crossPlotCol = None, None

            self.probeLabel.setText("<span style='color: #808080'>No data at cursor</span>")
            self.crossLineHorizontal.setVisible(False)
            self.crossLineVertical.setVisible(False)
            self.crossLineHorShadow.setVisible(False)
            self.crossLineVerShadow.setVisible(False)

            self.horCrossPlotItem.clear()
            self.verCrossPlotItem.clear()

            if self.slicedArray is not None and self.viewBox.sceneBoundingRect().contains(viewPos):

                # Calculate the row and column at the cursor.
                scenePos = self.viewBox.mapSceneToView(viewPos)
                row, col = round(scenePos.y()), round(scenePos.x())
                row, col = int(row), int(col)  # Needed in Python 2
                nRows, nCols = self.slicedArray.shape

                if (0 <= row < nRows) and (0 <= col < nCols):
                    self.viewBox.setCursor(Qt.CrossCursor)

                    self.crossPlotRow, self.crossPlotCol = row, col
                    index = tuple([row, col])
                    valueStr = to_string(self.slicedArray.data[index],
                                         masked=self.slicedArray.maskAt(index),
                                         maskFormat='&lt;masked&gt;')

                    txt = "({}, {}) = ({:d}, {:d}) {} {} = {}".format(
                        self.collector.rtiInfo['x-dim'], self.collector.rtiInfo['y-dim'],
                        col, row, RIGHT_ARROW, self.collector.rtiInfo['name'], valueStr)
                    self.probeLabel.setText(txt)

                    # Show cross section at the cursor pos in the line plots
                    if self.config.horCrossPlotCti.configValue:
                        self.crossLineHorShadow.setVisible(True)
                        self.crossLineHorizontal.setVisible(True)
                        self.crossLineHorShadow.setPos(row)
                        self.crossLineHorizontal.setPos(row)

                        # Line plot of cross section row.
                        # First determine which points are connected or separated by masks/nans.
                        rowData = self.slicedArray.data[row, :]
                        connected = np.isfinite(rowData)
                        if is_an_array(self.slicedArray.mask):
                            connected = np.logical_and(connected, ~self.slicedArray.mask[row, :])
                        else:
                            connected = (np.zeros_like(rowData)
                                         if self.slicedArray.mask else connected)

                        # Replace mask by Nans. Only doing when not showing lines to hack around PyQtGraph issue 1057
                        # See comment in PgLinePlot1d._drawContents for a more detailed explanation
                        # TODO: reuse imageItem data array when this hack is no longer necessary
                        if not self.config.crossPenCti.lineCti.configValue:
                            rowData = replaceMaskedValueWithFloat(rowData, np.logical_not(connected),
                                                                  np.nan, copyOnReplace=True)

                        # Replace infinite value with nans because PyQtGraph can't handle them
                        rowData = replaceMaskedValueWithFloat(rowData, np.isinf(rowData),
                                                              np.nan, copyOnReplace=True)

                        horPlotDataItem = self.config.crossPenCti.createPlotDataItem()
                        # TODO: try to use connect='finite' when the hack above is no longer necessary. In that case
                        # test with array_masked test data
                        horPlotDataItem.setData(rowData, connect=connected)
                        self.horCrossPlotItem.addItem(horPlotDataItem)

                        # Vertical line in hor-cross plot
                        crossLineShadow90 = pg.InfiniteLine(angle=90, movable=False,
                                                            pen=self.crossShadowPen)
                        crossLineShadow90.setPos(col)
                        self.horCrossPlotItem.addItem(crossLineShadow90, ignoreBounds=True)
                        crossLine90 = pg.InfiniteLine(angle=90, movable=False, pen=self.crossPen)
                        crossLine90.setPos(col)
                        self.horCrossPlotItem.addItem(crossLine90, ignoreBounds=True)

                        if show_data_point:
                            crossPoint90 = pg.PlotDataItem(symbolPen=self.crossPen)
                            crossPoint90.setSymbolBrush(QtGui.QBrush(
                                self.config.crossPenCti.penColor))
                            crossPoint90.setSymbolSize(10)
                            crossPoint90.setData((col,), (rowData[col],))
                            self.horCrossPlotItem.addItem(crossPoint90, ignoreBounds=True)

                        self.config.horCrossPlotRangeCti.updateTarget()  # update auto range
                        del rowData  # defensive programming

                    if self.config.verCrossPlotCti.configValue:
                        self.crossLineVerShadow.setVisible(True)
                        self.crossLineVertical.setVisible(True)
                        self.crossLineVerShadow.setPos(col)
                        self.crossLineVertical.setPos(col)

                        # Line plot of cross section row.
                        # First determine which points are connected or separated by masks/nans.
                        colData = self.slicedArray.data[:, col]
                        connected = np.isfinite(colData)
                        if is_an_array(self.slicedArray.mask):
                            connected = np.logical_and(connected, ~self.slicedArray.mask[:, col])
                        else:
                            connected = (np.zeros_like(colData)
                                         if self.slicedArray.mask else connected)

                        # Replace mask by Nans. Only doing when not showing lines to hack around PyQtGraph issue 1057
                        # See comment in PgLinePlot1d._drawContents for a more detailed explanation
                        if not self.config.crossPenCti.lineCti.configValue:
                            colData = replaceMaskedValueWithFloat(colData, np.logical_not(connected),
                                                                  np.nan, copyOnReplace=True)

                        # Replace infinite value with nans because PyQtGraph can't handle them
                        colData = replaceMaskedValueWithFloat(colData, np.isinf(colData),
                                                              np.nan, copyOnReplace=True)

                        verPlotDataItem = self.config.crossPenCti.createPlotDataItem()
                        verPlotDataItem.setData(colData, np.arange(nRows), connect=connected)
                        self.verCrossPlotItem.addItem(verPlotDataItem)

                        # Horizontal line in ver-cross plot
                        crossLineShadow0 = pg.InfiniteLine(angle=0, movable=False,
                                                           pen=self.crossShadowPen)
                        crossLineShadow0.setPos(row)
                        self.verCrossPlotItem.addItem(crossLineShadow0, ignoreBounds=True)
                        crossLine0 = pg.InfiniteLine(angle=0, movable=False, pen=self.crossPen)
                        crossLine0.setPos(row)
                        self.verCrossPlotItem.addItem(crossLine0, ignoreBounds=True)

                        if show_data_point:
                            crossPoint0 = pg.PlotDataItem(symbolPen=self.crossPen)
                            crossPoint0.setSymbolBrush(QtGui.QBrush(self.config.crossPenCti.penColor))
                            crossPoint0.setSymbolSize(10)
                            crossPoint0.setData((colData[row],), (row,))
                            self.verCrossPlotItem.addItem(crossPoint0, ignoreBounds=True)

                        self.config.verCrossPlotRangeCti.updateTarget()  # update auto range
                        del colData  # defensive programming

        except Exception as ex:
            # In contrast to _drawContents, this function is a slot and thus must not throw
            # exceptions. The exception is logged. Perhaps we should clear the cross plots, but
            # this could, in turn, raise exceptions.
            if DEBUGGING:
                raise
            else:
                logger.exception(ex)
