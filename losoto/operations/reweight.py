#!/usr/bin/env python
# -*- coding: utf-8 -*-

from losoto.operations_lib import *
import logging

logging.debug('Loading REWEIGHT module.')

def run_parser(soltab, parser, step):
    weightVal = parser.getfloat( step, 'weightVal', 1. )
    soltabImport = parser.getstr( step, 'soltabImport', '' )
    flagBad = parser.getbool( step, 'flagBad', False )
    return run(soltab, weightVal, soltabImport, flagBad)


def rolling_window_lastaxis(a, window):
    """Directly taken from Erik Rigtorp's post to numpy-discussion.
    <http://www.mail-archive.com/numpy-discussion@scipy.org/msg29450.html>"""
    import numpy as np

    if window < 1:
       raise ValueError, "`window` must be at least 1."
    if window > a.shape[-1]:
       raise ValueError, "`window` is too long."
    shape = a.shape[:-1] + (a.shape[-1] - window + 1, window)
    strides = a.strides + (a.strides[-1],)
    return np.lib.stride_tricks.as_strided(a, shape=shape, strides=strides)


def nancircstd(samples, axis=None, is_phase=True):
    """
    Compute the circular standard deviation

    Based on scipy.stats.circstd

    Parameters
    ----------
    imag : array_like
        Input array.
    axis : int, optional
        Axis along which standard deviations are computed.  The default is
        to compute the standard deviation of the flattened array.
    is_phase : bool, optional
        If True, samples are assumed to be phases. If False, they are assumed
        to be either real or imaginary values

    Returns
    -------
    circstd : float
        Circular standard deviation.
    """
    import numpy as np

    if is_phase:
        x1 = np.sin(samples)
        x2 = np.cos(samples)
    else:
        x1 = samples
        x2 = np.sqrt(1.0 - x1**2)
    R = np.hypot(np.nanmean(x1, axis=axis), np.nanmean(x2, axis=axis))

    return np.sqrt(-2*np.log(R))


def estimate_weights_window(sindx, vals, nmedian, nstddev, type, outQueue):
    """
    Set weights using a median-filter method

    Parameters
    ----------
    sindx: int
        Index of station
    vals: array
        Array of values
    nmedian: odd int
        Size of median time window
    nstddev: odd int
        Size of stddev time window
    typ: str
        Type of values (e.g., 'phase')

    """
    import numpy as np
    from scipy.ndimage import generic_filter

    pad_width = [(0, 0)] * len(vals.shape)
    pad_width[-1] = ((nmedian-1)/2, (nmedian-1)/2)
    if type == 'phase':
        # Median smooth and subtract to de-trend
        if nmedian > 0:
            # Convert to real/imag
            real = np.cos(vals)
            pad_real = np.pad(real, pad_width, 'constant', constant_values=(np.nan,))
            med_real = np.nanmedian(rolling_window_lastaxis(pad_real, nmedian), axis=-1)
            real -= med_real
            real[real < -1.0] = -1.0
            real[real > 1.0] = 1.0

            imag = np.sin(vals)
            pad_imag = np.pad(imag, pad_width, 'constant', constant_values=(np.nan,))
            med_imag = np.nanmedian(rolling_window_lastaxis(pad_imag, nmedian), axis=-1)
            imag -= med_imag
            imag[imag < -1.0] = -1.0
            imag[imag > 1.0] = 1.0

            # Calculate standard deviations
            pad_width[-1] = ((nstddev-1)/2, (nstddev-1)/2)
            pad_real = np.pad(real, pad_width, 'constant', constant_values=(np.nan,))
            stddev1 = nancircstd(rolling_window_lastaxis(pad_real, nstddev), axis=-1, is_phase=False)
            pad_imag = np.pad(imag, pad_width, 'constant', constant_values=(np.nan,))
            stddev2 = nancircstd(rolling_window_lastaxis(pad_imag, nstddev), axis=-1, is_phase=False)
            stddev = stddev1 + stddev2
        else:
            phase = normalize_phase(vals)

            # Calculate standard deviation
            pad_width[-1] = ((nstddev-1)/2, (nstddev-1)/2)
            pad_phase = np.pad(phase, pad_width, 'constant', constant_values=(np.nan,))
            stddev = nancircstd(rolling_window_lastaxis(pad_phase, nstddev), axis=-1)
    else:
        # Median smooth and subtract to de-trend
        if nmedian > 0:
            pad_vals = np.pad(vals, pad_width, 'constant', constant_values=(np.nan,))
            med = np.nanmedian(rolling_window_lastaxis(pad_vals, nmedian), axis=-1)
            vals -= med

        # Calculate standard deviation in larger window
        pad_width[-1] = ((nstddev-1)/2, (nstddev-1)/2)
        pad_vals = np.pad(vals, pad_width, 'constant', constant_values=(np.nan,))
        stddev = np.nanstd(rolling_window_lastaxis(pad_vals, nstddev), axis=-1)

    # Check for periods where standard deviation is zero or NaN and replace
    # with min value to prevent inf in the weights. Also limit weights to
    # float16
    zero_scatter_ind = np.where(np.logical_or(np.isnan(stddev), stddev == 0.0))
    if len(zero_scatter_ind[0]) > 0:
        good_ind = np.where(~np.logical_or(np.isnan(stddev), stddev == 0.0))
        stddev[zero_scatter_ind] = np.min(stddev[good_ind])
    if nmedian > 0:
        fudge_factor = 2.0 # factor to compensate for smoothing
    else:
        fudge_factor = 1.0
    w = 1.0 / np.square(stddev*fudge_factor)
    w[w > 65504.0] = 65504.0

    outQueue.put([sindx, w])


def run( soltab, method='uniform', weightVal=1., nmedian=3, nstddev=251,
    soltabImport='', flagBad=False, ncpu=0 ):
    """
    This operation resets the weight vals

    Parameters
    ----------
    method : str, optional
        One of 'uniform' (single value) or 'window' (sliding window in time).
    weightVal : float, optional
        Set weights to this values (0=flagged), by default 1.
    nmedian : odd int, optional
        Median window size in number of timeslots for 'window' method.
        If nonzero, a median-smoothed version of the input values is
        subtracted to detrend them. If 0, no smoothing or subtraction is
        done.
    nstddev : odd int, optional
        Standard deviation window size in number of timeslots for 'window' method.
    soltabImport : str, optional
        Name of a soltab. Copy weights from this soltab, by default do not copy.
    flagBad : bool, optional
        Re-apply flags to bad values, by default False.
    """

    import numpy as np

    logging.info("Reweighting soltab: "+soltab.name)

    if soltabImport != '':
        solset = soltab.getSolset()
        soltabI = solset.getSoltab(soltabImport)
        soltabI.selection = soltab.selection

        weights, axes = soltab.getValues(weight = True)
        weightsI, axesI = soltabI.getValues(weight = True)
        if axes.keys() != axesI.keys() or weights.shape != weightsI.shape:
            logging.error('Impossible to merge two tables with different axes values')
            return 1
        weightsI[ np.where(weights == 0) ] = 0.
        soltab.setValues(weightsI, weight=True)
        soltab.addHistory('WEIGHT imported from '+soltabI.name+'.')
    else:
        if method == 'uniform':
            weights = weightVal
            soltab.addHistory('REWEIGHTED to '+str(weightVal)+'.')
        elif method == 'window':
            if ncpu == 0:
                import multiprocessing
                ncpu = multiprocessing.cpu_count()
            if nmedian !=0 and nmedian % 2 == 0:
                logging.error('nmedian must be odd')
                return 1
            if nstddev % 2 == 0:
                logging.error('nstddev must be odd')
                return 1

            tindx = soltab.axesNames.index('time')
            antindx = soltab.axesNames.index('ant')
            vals = soltab.val[:].swapaxes(antindx, 0)
            if tindx == 0:
                tindx = antindx
            mpm = multiprocManager(ncpu, estimate_weights_window)
            for sindx, sval in enumerate(vals):
                if np.all(sval == 0.0):
                    # skip reference station
                    continue
                mpm.put([sindx, sval.swapaxes(tindx-1, -1), nmedian, nstddev, soltab.getType()])
            mpm.wait()
            weights = np.ones(vals.shape)
            for (sindx, w) in mpm.get():
                weights[sindx, :] = w.swapaxes(-1, tindx-1)
            weights = weights.swapaxes(0, antindx)

            soltab.addHistory('REWEIGHTED using sliding window with nmedian={0} '
                'and nstddev={1} timeslots'.format(nmedian, nstddev))
        soltab.setValues(weights, weight=True)

    if flagBad:
        weights = soltab.getValues(weight = True, retAxesVals = False)
        vals = soltab.getValues(retAxesVals = False)
        if soltab.getType() == 'amplitude': weights[np.where(vals == 1)] = 0
        else: weights[np.where(vals == 0)] = 0
        soltab.setValues(weights, weight=True)

    return 0
