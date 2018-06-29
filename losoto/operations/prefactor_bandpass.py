#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from losoto.lib_operations import *

logging.debug('Loading PREFACTOR_BANDPASS module.')

def _run_parser(soltab, parser, step):
    chanWidth = parser.getstr( step, 'chanWidth')
    BadSBList = parser.getstr( step, 'BadSBList' , '')
    autoflag = parser.getbool( step, 'autoFlag', False )
    nsigma = parser.getfloat( step, 'nSigma', 5.0 )
    max_flagged_fraction = parser.getfloat( step, 'maxFlaggedFraction', 0.5 )
    max_stddev = parser.getfloat( step, 'maxStddev', 0.006 )
    ncpu = parser.getint( '_global', 'ncpu', 0 )
    return run(soltab, chanWidth, BadSBList)


def _savitzky_golay(y, window_size, order, deriv=0, rate=1):
    """Smooth (and optionally differentiate) data with a Savitzky-Golay filter.
    The Savitzky-Golay filter removes high frequency noise from data.
    It has the advantage of preserving the original shape and
    features of the signal better than other types of filtering
    approaches, such as moving averages techniques.

    Parameters
    ----------
    y : array_like, shape (N,)
        the values of the time history of the signal.
    window_size : int
        the length of the window. Must be an odd integer number.
    order : int
        the order of the polynomial used in the filtering.
        Must be less then `window_size` - 1.
    deriv: int
        the order of the derivative to compute (default = 0 means only smoothing)

    Returns
    -------
    ys : ndarray, shape (N)
        the smoothed signal (or it's n-th derivative).

    Notes
    -----
    The Savitzky-Golay is a type of low-pass filter, particularly
    suited for smoothing noisy data. The main idea behind this
    approach is to make for each point a least-square fit with a
    polynomial of high order over a odd-sized window centered at
    the point.

    Examples
    --------
    t = np.linspace(-4, 4, 500)
    y = np.exp( -t**2 ) + np.random.normal(0, 0.05, t.shape)
    ysg = savitzky_golay(y, window_size=31, order=4)
    import matplotlib.pyplot as plt
    plt.plot(t, y, label='Noisy signal')
    plt.plot(t, np.exp(-t**2), 'k', lw=1.5, label='Original signal')
    plt.plot(t, ysg, 'r', label='Filtered signal')
    plt.legend()
    plt.show()

    References
    ----------
    .. [1] A. Savitzky, M. J. E. Golay, Smoothing and Differentiation of
       Data by Simplified Least Squares Procedures. Analytical
       Chemistry, 1964, 36 (8), pp 1627-1639.
    .. [2] Numerical Recipes 3rd Edition: The Art of Scientific Computing
       W.H. Press, S.A. Teukolsky, W.T. Vetterling, B.P. Flannery
       Cambridge University Press ISBN-13: 9780521880688
    """
    import numpy as np
    from math import factorial

    try:
        window_size = np.abs(np.int(window_size))
        order = np.abs(np.int(order))
    except ValueError, msg:
        raise ValueError("window_size and order have to be of type int")
    if window_size % 2 != 1 or window_size < 1:
        raise TypeError("window_size size must be a positive odd number")
    if window_size < order + 2:
        raise TypeError("window_size is too small for the polynomials order")
    order_range = range(order+1)
    half_window = (window_size -1) // 2
    # precompute coefficients
    b = np.mat([[k**i for i in order_range] for k in range(-half_window, half_window+1)])
    m = np.linalg.pinv(b).A[deriv] * rate**deriv * factorial(deriv)
    # pad the signal at the extremes with
    # values taken from the signal itself
    firstvals = y[0] - np.abs( y[1:half_window+1][::-1] - y[0] )
    lastvals = y[-1] + np.abs(y[-half_window-1:-1][::-1] - y[-1])
    y = np.concatenate((firstvals, y, lastvals))
    return np.convolve( m[::-1], y, mode='valid')


def _B(x, k, i, t, extrap, invert):
    if k == 0:
        if extrap:
            if invert:
                return -1.0
            else:
                return 1.0
        else:
            return 1.0 if t[i] <= x < t[i+1] else 0.0
    if t[i+k] == t[i]:
       c1 = 0.0
    else:
       c1 = (x - t[i])/(t[i+k] - t[i]) * _B(x, k-1, i, t, extrap, invert)
    if t[i+k+1] == t[i+1]:
       c2 = 0.0
    else:
       c2 = (t[i+k+1] - x)/(t[i+k+1] - t[i+1]) * _B(x, k-1, i+1, t, extrap, invert)
    return c1 + c2


def _bspline(x, t, c, k):
    n = len(t) - k - 1
    assert (n >= k+1) and (len(c) >= n)
    invert = False
    extrap = [False] * n
    if x >= t[n]:
        extrap[-1] = True
    elif x < t[k]:
        extrap[0] = True
        invert = False
    return sum(c[i] * _B(x, k, i, t, e, invert) for i, e in zip(range(n), extrap))


def _bandpass_HBA_low(freq, c1, c2, c3, c4, c5, c6, c7, c8, c9, c10):
    """
    Defines the functional form of the bandpass in terms of splines of degree 3

    The spline fit was done using LSQUnivariateSpline() on the median bandpass between
    120 MHz and 188 MHz. The knots were set by hand to acheive a good fit with a
    minimum number of parameters.

    Parameters
    ----------
    freq : array
        Array of frequencies
    c1-c9: float
        Spline coefficients

    Returns
    -------
    bandpass : list
        List of bandpass values as function of frequency
    """
    knots = np.array([1.20237732e+08, 1.20237732e+08, 1.20237732e+08, 1.20237732e+08,
                      1.30000000e+08, 1.38000000e+08, 1.48000000e+08, 1.60000000e+08,
                      1.68000000e+08, 1.78000000e+08, 1.87376404e+08, 1.87376404e+08,
                      1.87376404e+08, 1.87376404e+08])
    coeffs = np.array([c1, c2, c3, c4, c5, c6, c7, c8, c9, c10])
    return [_bspline(f, knots, coeffs, 3) for f in freq]


def _fit_bandpass(freq, logamp, sigma, band, do_fit=True):
    """
    Fits amplitudes with one of the bandpass functions

    The initial coefficients were determined from a LSQUnivariateSpline() fit on the
    median bandpass of the appropriate band. The allowable fitting ranges were set by
    hand through testing on a number of observations (to allow the bandpass function to
    adjust for the differences between stations but not to fit to RFI, etc.).

    Parameters
    ----------
    freq : array
        Array of frequencies
    amps : array
        Array of log10(amplitudes)
    sigma : array
        Array of sigma (1/weights**2)
    band : str
        Band name ('hba_low', etc.)
    do_fit : bool, optional
        If True, the fitting is done. If False, the unmodified model bandpass is returned

    Returns
    -------
    fit_parms, bandpass : list, list
        List of best-fit parameters, List of bandpass values as function of frequency
    """
    from scipy.optimize import curve_fit

    if band.lower() == 'hba_low':
        bandpass_function = _bandpass_HBA_low
        init_coeffs = np.array([-0.01460369, 0.05062699, 0.02827004, 0.03738518,
                                -0.05729109, 0.02303295, -0.03550487, -0.0803113,
                                -0.2394929, -0.358301])
        bounds_deltas = [0.06, 0.05, 0.04, 0.04, 0.04, 0.04, 0.04, 0.04, 0.05, 0.06]
    else:
        print('The "{}" band is not supported'.format(band))
        sys.exit(1)

    if do_fit:
        lower = [c - b for c, b in zip(init_coeffs, bounds_deltas)]
        upper = [c + b for c, b in zip(init_coeffs, bounds_deltas)]
        param_bounds = (lower, upper)
        popt, pcov = curve_fit(bandpass_function, freq, logamp, sigma=sigma,
                               bounds=param_bounds)
        return popt, bandpass_function(freq, *tuple(popt))
    else:
        return None, bandpass_function(freq, *tuple(init_coeffs))


def _flag_amplitudes(freqs, amps, weights, nsigma, max_flagged_fraction, max_stddev,
                     plot, s, outQueue):
    """
    Flags bad amplitude solutions relative to median bandpass (in log space) by setting
    the corresponding weights to 0.0

    Parameters
    ----------
    freqs : array
        Array of frequencies
    amps : array
        Array of amplitudes as [time, ant, freq, pol]
    weights : array
        Array of weights as [time, ant, freq, pol]
    nsigma : float
        Number of sigma for flagging. Amplitudes outside of nsigma*stddev are flagged
    max_flagged_fraction : float
        Maximum allowable fraction of flagged frequencies. Stations with higher fractions
        will be completely flagged
    max_stddev : float
        Maximum allowable standard deviation
    plot : bool
        If True, the bandpass with flags and best-fit line is plotted for each station
    s : int
        Station index

    Returns
    -------
    indx, weights : int, array
        Station index, modified weights array
    """
    # Determine which band we're in
    if np.median(freqs) < 180e6 and np.median(freqs) > 110e6:
        band = 'hba_low'
        median_min = 75.0
        median_max = 200.0
    else:
        print('The median frequency of {} Hz is outside of any know band'.format(np.median(freqs)))
        sys.exit(1)

    # Skip fully flagged stations
    if np.all(weights == 0.0):
        outQueue.put([s, weights])
        return

    # Build arrays for fitting
    flagged = np.where(weights == 0.0)
    amps_flagged = amps.copy()
    amps_flagged[flagged] = np.nan
    sigma = np.sqrt(1.0 / weights)
    sigma[flagged] = 1e8

    # Iterate over polarizations
    npols = amps.shape[2] # number of polarizations
    for pol in range(npols):
        # take median over time and pol axes and divide out the median offset
        amps_div = np.nanmedian(amps_flagged[:, :, pol], axis=0)
        median_val = np.nanmedian(amps_div)
        amps_div /= median_val
        sigma_div = np.nanmedian(sigma[:, :, pol], axis=0)
        sigma_orig = sigma_div.copy()

        # Before doing the fitting, flag any solutions that deviate from the model bandpass by
        # a large factor to avoid biasing the first fit
        _, bp_sp = _fit_bandpass(freqs, np.log10(amps_div), sigma_div, band, do_fit=False)
        bad = np.where(np.abs(bp_sp - np.log10(amps_div)) > 0.2)
        sigma_div[bad] = 1e8

        # Iteratively fit and flag
        maxiter = 5
        niter = 0
        nflag = 0
        nflag_prev = -1
        while nflag != nflag_prev and niter < maxiter:
            p, bp_sp = _fit_bandpass(freqs, np.log10(amps_div), sigma_div, band)
            stdev_all = np.sqrt(np.average((bp_sp-np.log10(amps_div))**2, weights=(1/sigma_div)**2))
            stdev = min(max_stddev, stdev_all)
            bad = np.where(np.abs(bp_sp - np.log10(amps_div)) > nsigma*stdev)
            nflag = len(bad[0])
            if nflag == 0:
                break
            if niter > 0:
                nflag_prev = nflag
            sigma_div = sigma_orig.copy()  # reset flags to original ones
            sigma_div[bad] = 1e8
            niter += 1

        if plot:
            import matplotlib.pyplot as plt
            plt.plot(freqs, bp_sp, 'g-', lw=3)
            plt.plot(freqs, np.log10(amps_div), 'o', c='g')
            plt.plot(freqs[bad], np.log10(amps_div)[bad], 'o', c='r')
            plt.show()

        # Check whether entire station is bad (high stdev or high flagged fraction). If
        # so, flag all frequencies and polarizations
        if stdev_all > max_stddev * 5.0:
            # Station has very high stddev relative to median bandpass; flag it
            print('Flagging station {} due to high stddev'.format(s))
            weights[:, :, :] = 0.0
            break
        elif float(len(bad[0]))/float(len(freqs)) > max_flagged_fraction:
            # Station has high fraction of flagged frequencies; flag it
            print('Flagging station {} due to high flagged fraction'.format(s))
            weights[:, :, :] = 0.0
            break
        elif median_val < median_min or median_val > median_max:
            # Station has extreme median value; flag it
            print('Flagging station {} due to extreme median value'.format(s))
            weights[:, :, :] = 0.0
            break
        else:
            # Station is OK; flag solutions with high sigma values
            flagged = np.where(sigma_div > 1e3)
            weights[:, flagged[0], pol] = 0.0

    outQueue.put([s, weights])


def run(soltab, chanWidth, BadSBList = '', autoflag=False, nsigma=5.0,
        max_flagged_fraction=0.5, max_stddev=0.006, ncpu=0):
    """
    This operation for LoSoTo implements the Prefactor bandpass operation
    WEIGHT: flag-only compliant, no need for weight

    Parameters
    ----------
    chanWidth : str or float
        the width of each channel in the data from which solutions were obtained. Can be
        either a string like "48kHz" or a float in Hz
    BadSBList : str, optional
        a list of bad subbands that will be flagged
    autoflag : bool, optional
        If True, automatically flag bad frequencies and stations
    nsigma : float, optional
        Number of sigma for autoflagging. Amplitudes outside of nsigma*stddev are flagged
    max_flagged_fraction : float, optional
        Maximum allowable fraction of flagged frequencies for autoflagging. Stations with
        higher fractions will be completely flagged
    max_stddev : float, optional
        Maximum allowable standard deviation for autoflagging
    ncpu : int, optional
        Number of CPUs to use during autoflagging (0 = all)
    """
    import numpy as np
    import scipy
    import scipy.ndimage

    logging.info("Running prefactor_bandpass on: "+soltab.name)
    solset = soltab.getSolset()

    solType = soltab.getType()
    if solType != 'amplitude':
       logging.warning("Soltab type of "+soltab.name+" is: "+solType+" should be amplitude. Ignoring.")
       return 1

    if BadSBList == '':
      bad_sblist   = []
    else:
      bad_sblist = [int(SB) for SB in BadSBList.strip('\"\'').split(';')]

    amplitude_arraytmp = soltab.val[:] # axes are [time, ant, freq, pol]
    weights_arraytmp = soltab.weight[:] # axes are [time, ant, freq, pol]
    flagged = np.where(amplitude_arraytmp == 1.0)
    weights_arraytmp[flagged] = 0.0
    nfreqs = len(soltab.freq[:])
    ntimes = len(soltab.time[:])
    nants = len(soltab.ant[:])

    subbandHz = 195.3125e3
    if type(chanWidth) is str:
        letters = [1 for s in chanWidth[::-1] if s.isalpha()]
        indx = len(chanWidth) - sum(letters)
        unit = chanWidth[indx:]
        if unit.strip().lower() == 'hz':
            conversion = 1.0
        elif unit.strip().lower() == 'khz':
            conversion = 1e3
        elif unit.strip().lower() == 'mhz':
            conversion = 1e6
        else:
            logging.error("The unit on chanWidth was not understood.")
            raise ValueError("The unit on chanWidth was not understood.")
        chanWidthHz = float(chanWidth[:indx]) * conversion
    else:
        chanWidthHz = chanWidth
    offsetHz = subbandHz / 2.0 - 0.5 * chanWidthHz
    freqmin = np.min(soltab.freq[:]) + offsetHz # central frequency of first subband
    freqmax = np.max(soltab.freq[:]) + offsetHz # central frequency of last subband
    timeidx = np.arange(ntimes)
    SBgrid = np.floor((soltab.freq[:]-np.min(soltab.freq[:]))/subbandHz)
    freqs_new  = np.arange(freqmin, freqmax+100e3, subbandHz)
    amps_array_flagged = np.zeros( (nants, ntimes, len(freqs_new), 2), dtype='float')
    amps_array = np.zeros( (nants, ntimes, len(freqs_new), 2), dtype='float')
    weights_array =  np.ones( (nants, ntimes, len(freqs_new), 2), dtype='float')
    minscale = np.zeros( nants )
    maxscale = np.zeros( nants )

    if len(freqs_new) < 20:
        logging.error("Frequency span is less than 20 subbands! The filtering will not work!")
        logging.error("Please run the calibrator pipeline on the full calibrator bandwidth.")
        raise ValueError("Frequency span is less than 20 subbands! Amplitude filtering will not work!")
        pass

    # make a mapping of new frequencies to old ones
    freq_mapping = {}
    for fn in freqs_new:
        ind = np.where(np.logical_and(soltab.freq < fn+subbandHz/2.0, soltab.freq >= fn-subbandHz/2.0))
        freq_mapping['{}'.format(fn)] = ind

    # remove bad subbands specified by user
    logging.info("Have " + str(max(SBgrid)) + " subbands.")
    for bad_sb in bad_sblist:
        logging.info('Removing user-specified subband: ' + str(bad_sb))
        weights_arraytmp[:, :, bad_sb, :] = 0.0

    # remove bad solutions relative to the model bandpass
    if autoflag:
        if ncpu == 0:
            import multiprocessing
            ncpu = multiprocessing.cpu_count()
        mpm = multiprocManager(ncpu, _flag_amplitudes)
        for s in range(nants):
            mpm.put([soltab.freq[:], amplitude_arraytmp[:, s, :, :], weights_arraytmp[:, s, :, :],
                     nsigma, max_flagged_fraction, max_stddev, False, s])
        mpm.wait()
        for (s, w) in mpm.get():
            weights_arraytmp[:, s, :, :] = w

    # Now interpolate over flagged values
    for antenna_id in range(len(soltab.ant[:])):
        for time in range(len(soltab.time[:])):
            amp_xx_tmp = np.copy(amplitude_arraytmp[time, antenna_id, :, 0])
            amp_yy_tmp = np.copy(amplitude_arraytmp[time, antenna_id, :, 1])
            freq_tmp = soltab.freq[:]
            assert len(amp_xx_tmp[:]) == len(freq_tmp[:])
            mask_xx = np.not_equal(weights_arraytmp[time, antenna_id, :, 0], 0.0)
            if np.sum(mask_xx)>2:
                amps_xx_tointer = amp_xx_tmp[mask_xx]
                freq_xx_tointer = freq_tmp[mask_xx]
                amps_array_flagged[antenna_id, time, :, 0] = np.interp(freqs_new, freq_xx_tointer, amps_xx_tointer)
            elif time>0:
                amps_array_flagged[antenna_id, time, :, 0] = amps_array_flagged[antenna_id, (time-1), :, 0]
            mask_yy = np.not_equal(weights_arraytmp[time, antenna_id, :, 1], 0.0)
            if np.sum(mask_yy)>2:
                amps_yy_tointer = amp_yy_tmp[mask_yy]
                freq_yy_tointer = freq_tmp[mask_yy]
                amps_array_flagged[antenna_id, time, :, 1] = np.interp(freqs_new, freq_yy_tointer, amps_yy_tointer)
            elif time>0:
                amps_array_flagged[antenna_id, time, :, 1] = amps_array_flagged[antenna_id, (time-1), :, 1]

    ampsoutfile = open('calibrator_amplitude_array.txt','w')
    ampsoutfile.write('# Antenna name, Antenna ID, subband, XXamp, YYamp, frequency\n')
    for antenna_id in range(len(soltab.ant[:])):
        if np.all(weights_arraytmp[:, antenna_id, :, :] == 0.0):
            weights_array[antenna_id, :, :, :] = 0.0
        else:
            amp_xx = np.copy(amps_array_flagged[antenna_id, :, :, 0])
            amp_yy = np.copy(amps_array_flagged[antenna_id, :, :, 1])

            amp_xx = scipy.ndimage.filters.median_filter(amp_xx, (3,3))
            amp_xx = scipy.ndimage.filters.median_filter(amp_xx, (7,1))
            amp_yy = scipy.ndimage.filters.median_filter(amp_yy, (3,3))
            amp_yy = scipy.ndimage.filters.median_filter(amp_yy, (7,1))

            for i in range(len(freqs_new)):
                ampsoutfile.write('%s %s %s %s %s %s\n'%(soltab.ant[antenna_id], antenna_id,
                                                         i, np.median(amp_xx[:,i], axis=0),
                                                         np.median(amp_yy[:,i], axis=0),
                                                         freqs_new[i]))

            for time in range(len(soltab.time[:])):
                amps_array[antenna_id, time, :, 0] = np.copy(_savitzky_golay(amp_xx[time,:], 17, 2))
                amps_array[antenna_id, time, :, 1] = np.copy(_savitzky_golay(amp_yy[time,:], 17, 2))

            for i in range(len(freqs_new)):
                amps_array[antenna_id, :, i, 0] = np.median(amps_array[antenna_id, :, i, 0])
                amps_array[antenna_id, :, i, 1] = np.median(amps_array[antenna_id, :, i, 1])
                ind = freq_mapping['{}'.format(freqs_new[i])]
                if np.any(weights_arraytmp[:, antenna_id, ind, :] == 0.0):
                    weights_array[antenna_id, :, i, :] = 0.0

    # delete existing bandpass soltab if needed and write solutions
    try:
        new_soltab = solset.getSoltab('bandpass')
        new_soltab.delete()
    except:
        pass
    new_soltab = solset.makeSoltab(soltype='amplitude', soltabName='bandpass',
                             axesNames=['ant', 'freq', 'pol'], axesVals=[soltab.ant,
                             freqs_new, ['XX', 'YY']], vals=amps_array[:, 0, :, :],
                             weights=weights_array[:, 0, :, :])
    new_soltab.addHistory('CREATE (by PREFACTOR_BANDPASS operation)')

    return 0
