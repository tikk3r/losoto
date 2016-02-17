#!/usr/bin/python
# -*- coding: utf-8 -*-
import numpy as np
import numpy.ma as ma
import sys
import logging
from lofar.expion import baselinefitting as fitting


# from pylab import *
def ClockTEC_3rdorder_func(xarray, par):
    """clock tec fitting withextra parameter for third order ionospheric effects at lowest frequencies"""
    delay = np.array([par[1] * 1e-9]).flatten()  # in ns, array has dimension 1, even if scalar
    delayfact = 2 * np.pi * delay[:, np.newaxis] * xarray
    TEC = np.array([par[0]]).flatten()  # dTEC in TECU
    drefract = -8.4479745e9 * TEC[:, np.newaxis] / xarray
    TEC3rd = np.array([par[2]]).flatten()  # 3rd_order
    d3rd = 1e21* TEC3rd[:, np.newaxis] / xarray**3

    return drefract[:, np.newaxis,np.newaxis, :] + delayfact[np.newaxis,:,np.newaxis, :]+d3rd[np.newaxis,np.newaxis,:, :]

def ClockTECfunc(xarray, par):
    delay = np.array([par[1] * 1e-9]).flatten()  # in ns, array has dimension 1, even if scalar
    delayfact = 2 * np.pi * delay[:, np.newaxis] * xarray
    TEC = np.array([par[0]]).flatten()  # dTEC in TECU
    drefract = -8.4479745e9 * TEC[:, np.newaxis] / xarray
    if len(par) > 2:
        return drefract[:, np.newaxis, :] + delayfact[np.newaxis] + par[2]  # returns nTEC x nClock x nFreq

    return drefract[:, np.newaxis, :] + delayfact


def ClockTECfuncAllStations(xarray, par):
    delay = np.array([par[1] * 1e-9]).flatten()  # in ns, array has dimension 1, even if scalar
    delayfact = 2 * np.pi * delay[:, np.newaxis] * xarray
    # print "delayfact",delayfact.shape
    TEC = np.array([par[0]]).flatten()  # dTEC in TECU
    drefract = -8.4479745e9 * TEC[:, np.newaxis] / xarray
    # print "refract",drefract.shape
    if len(par) > 2:
        return drefract + delayfact + par[2][:, np.newaxis]  # returns nTEC x nClock x nFreq

    return drefract + delayfact


def getInitClock(data, freq):
    nF = freq.shape[0]
    avgdata = np.ma.sum(np.cos(data) + 1.j * np.sin(data), axis=0).swapaxes(0, -2)
    avgdata = np.ma.arctan2(np.imag(avgdata), np.real(avgdata))
    nSt = avgdata.shape[0]
    npol = avgdata.shape[2]
    for ist in xrange(nSt):
        for pol in xrange(npol):
            mymask = avgdata[ist, :, pol].mask
            if not hasattr(mymask, '__len__'):
                mymask = np.ones(avgdata[ist, :, pol].shape, dtype=bool) * mymask
            if avgdata[ist, :, pol].count() < 1:
                avgdata[ist, :, pol].mask[0] = False
            # logging.debug("mask station %d pol %d "%(ist,pol) +str(mymask))
            # logging.debug("average data station %d pol %d "%(ist,pol) +str(avgdata[ist,:,pol]))
            avgdata[ist, :, pol][~mymask] = np.float32(np.unwrap(avgdata[ist, :, pol][~mymask]))
            # logging.debug("average unwrapped data station %d pol %d "%(ist,pol) +str(avgdata[ist,:,pol]))
            # logging.debug("remainder " +str(np.remainder(avgdata[ist,:,pol]+np.pi,2*np.pi)-np.pi))
    A = np.ones((nF, 2), dtype=np.float)
    A[:, 1] = freq * 2 * np.pi * 1e-9
    return np.ma.dot(np.linalg.inv(np.dot(A.T, A)), np.ma.dot(A.T, avgdata).swapaxes(0, -2))


def unwrapPhases(phases,fitdata=None,maskrange=15):
    '''unwrap phases, remove jumps and get best match with fitdata'''
    mymask=phases.mask
    for nriter in range(2):
        if not fitdata is None and fitdata.shape==phases.shape:
            wraps=np.ma.round((phases-fitdata)/(2*np.pi))
            phases-=wraps*2*np.pi
            unmasked=np.copy(np.array(phases))

        if fitdata is None:
            unmasked=np.copy(np.array(phases))
            unmasked=np.unwrap(unmasked)
            wraps=np.ma.round((phases-unmasked)/(2*np.pi))
            phases-=wraps*2*np.pi
        maskpoints=np.where(mymask)[0]
        if maskpoints.shape[0]>0:
            Atmp=np.ones((maskrange,2),dtype=np.float64)
            Atmp[:,1]=np.arange(maskrange)
            Atmpinv=np.linalg.inv(np.dot(Atmp.T,Atmp))
        doreverse=False
        for i in maskpoints:
            if i<maskrange and i>0:
                unmasked[i]=unmasked[i-1]
                doreverse=True
            if i>=maskrange:
                #print "changing unmasked[",i,"]:",unmasked[i],"into",
                unmasked[i]=np.dot(np.dot(Atmpinv,np.dot(Atmp.T,unmasked[i-maskrange:i])),[1,maskrange])
                #print unmasked[i]
        if doreverse:
            for i in maskpoints[::-1]:
                if i<unmasked.shape[0]-1-maskrange:
                    #print "changing unmasked[",i,"]:",unmasked[i],"into",
                    unmasked[i]=np.dot(np.dot(Atmpinv,np.dot(Atmp.T,unmasked[i+1:i+maskrange+1])),[1,-1])    
                    #print unmasked[i],np.dot(Atmp.T,unmasked[i+1:i+maskrange+1])
        # detect jumps and remove them
        diffdata=unmasked[1:]-unmasked[:-1]
        #detect bad datapoints since they can destroy unwrapping (if the offset is close to np.pi)
        wrapflags=np.logical_and(np.absolute(diffdata[:-1])>0.4*np.pi,np.absolute(diffdata[1:])>0.4*np.pi)
        newmask=np.zeros_like(diffdata,dtype=bool)
        newmask[:-1]=wrapflags
        diffdata=np.ma.array(diffdata,mask=newmask)
        # use 2.5 pi for calculating jumps, tomake sureyou have a real 2pi jump,instead of a sequence of 2 bad datapoints with order 1pi jump. yes I have seen those in LBA calibrator data
        phases[1:]-=np.ma.cumsum(np.ma.round(diffdata/(2.5*np.pi)))*2*np.pi  
        #wrapflags=np.logical_and(np.absolute(np.ma.ediff1d(phases)[:-1])>0.2*np.pi,np.absolute(np.ma.ediff1d(phases)[1:])>0.2*np.pi)
        mymask[1:-1]=np.logical_or(mymask[1:-1],wrapflags)
        phases.mask=mymask
        # get best match with fitdata
        if fitdata is None:
            #average around 0
            phases-=np.ma.round(np.ma.average(phases)/(2*np.pi))*np.pi*2
        else:
    
            phases-=np.ma.round(np.ma.average(phases-fitdata)/(2*np.pi))*np.pi*2
        if np.sum(wrapflags)==0:
            return phases
    return phases


def getInitPar(
    data,
    freqs, 
    nrTEC=40,
    nrClock=40,
    nrthird=0,
    initsol=[]
    ):
    if nrthird>0:
        A=np.ma.zeros((freqs.shape[0],3),dtype=np.float64)
        A[:,1]=2*np.pi*1e-9*freqs
        A[:,0]=-8.44797245e9/freqs
        A[:,2]=-1.e21/freqs**3
    else:
        A=np.ma.zeros((freqs.shape[0],2),dtype=np.float64)
        A[:,1]=2*np.pi*1e-9*freqs
        A[:,0]=-8.44797245e9/freqs
    a=np.mgrid[int(-nrTEC/2):int(nrTEC/2)+1,-int(nrClock/2):int(nrClock/2)+1]
    if len(initsol)>=2 and not (initsol[0]==0 and initsol[1]==0)  :
        fitdata=np.dot(initsol,A.T)
        data=unwrapPhases(data,fitdata)
    else:
        data=unwrapPhases(data)
        steps = np.ma.dot(np.ma.dot(np.linalg.inv(np.ma.dot(A[:,:2].T, A[:,:2])), A[:,:2].T), 2 * np.pi * np.ones((freqs.shape[0], ), dtype=np.float))
        par=np.ma.dot(np.linalg.inv(np.ma.dot(A[:,:2].T,A[:,:2])),np.ma.dot(A[:,:2].T,data))
        #get parameters close to 0
        data-=np.round(np.average(np.round(par/steps)))*2*np.pi
        par=np.ma.dot(np.linalg.inv(np.ma.dot(A[:,:2].T,A[:,:2])),np.ma.dot(A[:,:2].T,data))
        nrTEC+=np.abs(np.round(par[0]/steps[0]))
        nrClock+=np.abs(np.round(par[1]/steps[1]))

    A=np.ma.array(A,mask=np.tile(data.mask,(A.shape[1],1)).T)
    steps = np.ma.dot(np.ma.dot(np.linalg.inv(np.ma.dot(A[:,:2].T, A[:,:2])), A[:,:2].T), 2 * np.pi * np.ones((freqs.shape[0], ), dtype=np.float))
    #get initial guess, first only for first two parameters
    par=np.ma.dot(np.linalg.inv(np.ma.dot(A[:,:2].T,A[:,:2])),np.ma.dot(A[:,:2].T,data))
    
    #print "intial guess",par,"min 0",a[0][0,0]*steps[0]+par[0],"max 0",a[0][-1,0]*steps[0]+par[0],"min 1",a[1][0,0]*steps[1]+par[1],"max 1",a[1][0,-1]*steps[1]+par[1]
    bigdata=np.concatenate(tuple([a[i][np.newaxis,:]*steps[i]+par[i] for i  in range(2)]),axis=0).transpose(1,2,0)
    diffdata=np.dot(bigdata,A[:,:2].T)
    diffdata-=data[np.newaxis,np.newaxis]
    idx=np.unravel_index(np.argmin(np.ma.var(diffdata,axis=-1)),diffdata.shape[:-1])     
    par=bigdata[idx]
    fitdata=np.dot(par,A[:,:2].T)
    data=unwrapPhases(data,fitdata)
    #now add third parameter if needed:
    if nrthird>0:
        steps = np.ma.dot(np.ma.dot(np.linalg.inv(np.ma.dot(A.T, A)), A.T), 2 * np.pi * np.ones((freqs.shape[0], ), dtype=np.float))
        par=np.ma.dot(np.linalg.inv(np.ma.dot(A.T,A)),np.ma.dot(A.T,data))
        a=np.mgrid[max(-1,int(-nrTEC/2)):min(2,int(nrTEC/2)+1),max(-1,int(-nrClock/2)):min(2,int(nrClock/2)+1),-int(nrthird/2):int(nrthird/2)+1] #assume dTEC and dClock are already close
        bigdata=np.concatenate(tuple([a[i][np.newaxis,:]*steps[i]+par[i] for i  in range(3)]),axis=0).transpose(1,2,3,0)
        diffdata=np.ma.dot(bigdata,A.T)
        diffdata-=data[np.newaxis,np.newaxis,np.newaxis]
        idx=np.unravel_index(np.argmin(np.ma.var(diffdata,axis=-1)),diffdata.shape[:-1])     
        par=bigdata[idx]
        fitdata=np.dot(par,A.T)
        data=unwrapPhases(data,fitdata)
    return par,data


def getClockTECFit(
    ph,
    freq,
    stations,
    initSol=[],
    returnResiduals=True,
    chi2cut=1e8,
    fit3rdorder=False
    ):
    nT = ph.shape[0]
    nF = freq.shape[0]
    nSt = ph.shape[2]
    data = ph
    tecarray = np.zeros((nT, nSt), dtype=np.float32)
    clockarray = np.zeros((nT, nSt), dtype=np.float32)

    if returnResiduals:
        residualarray = np.zeros((nT, nF, nSt), dtype=np.float32)
    if fit3rdorder:
        tec3rdarray= np.zeros((nT, nSt), dtype=np.float32)
    A = np.ones((nF, 2+fit3rdorder), dtype=np.float)
    A[:, 1] = freq * 2 * np.pi * 1e-9
    A[:, 0] = -8.44797245e9 / freq
    if fit3rdorder:
        A[:, 2] = -1e21 / freq**3
    steps = np.ma.dot(np.ma.dot(np.linalg.inv(np.ma.dot(A.T, A)), A.T), 2 * np.pi * np.ones((freq.shape[0], ), dtype=np.float)) 
    succes=False
    initprevsol=np.zeros(nSt,dtype=bool)
    nrFail=np.zeros(nSt,dtype=int)
    sol = np.zeros((nSt, 2+fit3rdorder), dtype=np.float)
    prevsol = np.zeros_like(sol)
    n3rd=0
    for itm in xrange(nT):
        datatmp=np.ma.copy(data[itm, :])
        if itm == 0 or not succes:
            for ist in xrange(nSt):
                if itm == 0 or not initprevsol[ist]:
                    if hasattr(initSol, '__len__') and len(initSol) > ist:
                        sol[ist,:initSol[ist].shape[0]]=initSol[ist]
                        ndt=1
                        ndtec=1
                        if fit3rdorder:
                            n3rd=1
                    else:
                        if fit3rdorder:
                            n3rd=200
                        if 'CS' in stations[ist]:
                            ndt=4
                            ndtec=10
                            if 'LBA' in stations[ist]:
                                ndt=2
                                ndtec=40
                        else:
                            if 'RS' in stations[ist]:
                                ndt=200
                                ndtec=80
                            else:
                                # large TEC variation for EU stations
                                ndt=200
                                ndtec=160
                            if 'LBA' in stations[ist]:
                                 ndt=60
                                 # no init clock possible due to large TEC effect
                                 #stepsize of dtec is small
                                 ndtec=320
                else:
                    # further steps with non success
                    sol[ist, :] = prevsol[ist, :]
                    ndtec=min(nrFail[ist]+1,100)
                    if not 'CS' in stations[ist]:
                        ndt=min(nrFail[ist]+1,200)
                    else:
                        ndt=min(nrFail[ist]+1,4)
                    if fit3rdorder:
                        n3rd=min(nrFail[ist]+1,200)
                datatmpist = datatmp[:, ist]
                if datatmpist.count() / float(nF) > 0.5:
                    # do brutforce and update data, unwrp pdata,update flags
                    if itm%100==0:
                    #if itm<500:
                        logging.debug("Getting init par for time %d:station %d ntec %d ndt %d n3rd %d"%(itm,ist,ndtec,ndt,n3rd)+str(sol[ist]))
                    par,datatmp[:, ist] = getInitPar(datatmpist, freq,nrTEC=ndtec,nrClock=ndt,nrthird=n3rd,initsol=sol[ist,:])
                    sol[ist, :] = par[:]
                if itm%100==0:
                #if itm<500:
                    logging.debug("Getting init par for station %d:%d "%(itm,ist)+str(sol[ist]))
        for ist in xrange(nSt):
            #now do the real fitting
            datatmpist=datatmp[:,ist]
            if datatmpist.count() / float(nF) < 0.5:
                logging.debug("Too many data points flagged t=%d st=%d flags=%d"%(itm,ist,data[itm,:,ist].count()) + str(sol[ist]))
                sol[ist] = [-10.,]*sol.shape[1]
                continue
            fitdata=np.dot(sol[ist],A.T)
            datatmpist=unwrapPhases(datatmpist,fitdata)
            if itm%100==0:
            #if itm<500:
                logging.debug(" init par for station itm %d:%d "%(itm,ist)+str(sol[ist]))
            mymask=datatmpist.mask
            maskedfreq=np.ma.array(freq,mask=mymask)
            A2=np.ma.array(A,mask=np.tile(mymask,(A.shape[1],1)).T)
            sol[ist] = np.ma.dot(np.linalg.inv(np.ma.dot(A2.T, A2)), np.ma.dot(A2.T, datatmpist)).T
            if initprevsol[ist] and np.abs((sol[ist,1]-prevsol[ist,1])/steps[1])>0.5 and (np.abs((sol[ist,1]-prevsol[ist,1])/steps[1])>0.75 or np.abs(np.sum((sol[ist]-prevsol[ist])/steps,axis=-1))>0.5*A2.shape[0]):
                #logging.debug("removing jumps, par for station %d , itm %d"%(ist,itm)+str(sol[ist])+str(prevsol[ist])+str(steps))
                sol[ist,:]-=np.round((sol[ist,1]-prevsol[ist,1])/steps[1])*steps
                #logging.debug("removed jumps, par for station %d "%ist+str(sol[ist])+str(prevsol[ist]))
            if itm%100==0:
            #if itm<500:
                logging.debug("par for station itm %d:%d "%(itm,ist)+str(sol[ist]))
         # calculate chi2 per station
        residual = data[itm] - np.dot(A, sol.T)
        tmpresid = residual - residual[:, 0][:, np.newaxis]  # residuals relative to station 0
        residual = np.ma.remainder(tmpresid + np.pi, 2 * np.pi) - np.pi
        chi2 = np.ma.sum(np.square(np.degrees(residual)), axis=0) / nF

        if returnResiduals:
            residualarray[itm] = residual

        chi2select = np.logical_or(np.array(chi2 > chi2cut), sol[:, 0] < -5) # select bad points
        chi2select = np.logical_or(chi2select,initprevsol*np.sum(np.abs((sol-prevsol)/steps),axis=-1)>(0.3*sol.shape[1]*(1+nrFail))) #also discard data where there is a "half" jump for any parameter wrst the previous solution (if previous solution exists). Multiply with number of fails, since after a large number of fails there is no clear match with the previous solution expected anyway...
        if np.any(chi2select):
            #logging.debug('high chi2 of fit, itm: %d %d ' % (itm, np.sum(chi2select)) + str(sol[chi2select]) + 'prevsol'+str(prevsol[chi2select])+'stations:' + str(np.arange(nSt)[chi2select]) + ' chi2 ' + str(chi2[chi2select]))
            logging.debug('High chi2 of fit, itm: %d %d ' % (itm, np.sum(chi2select)) + 'stations:' + str(np.arange(nSt)[chi2select]))
            succes = False
            nrFail[chi2select] += 1
            nrFail[~chi2select] = 0
            prevsol[np.logical_and(initprevsol == False,chi2select==False)] = sol[np.logical_and(initprevsol == False,chi2select==False)]  # compensate missing prevsol at first rounds
            prevsol[~chi2select] = 0.5 * prevsol[~chi2select] + 0.5 * sol[~chi2select]  # init solution to 0.5 * this solution + 0.5 previous solution
            initprevsol[~chi2select] = True # once is True it never becomes False
        else:
            # prevsol=np.copy(sol)
            prevsol[initprevsol==False] = sol[initprevsol == False]  # compensate missing prevsol at first rounds
            prevsol = 0.5 * prevsol + 0.5 * np.copy(sol)
            succes = True
            initprevsol = np.ones(nSt, dtype=bool)
            nrFail = np.zeros(sol.shape[0], dtype=int)
        tecarray[itm] = sol[:, 0]
        clockarray[itm] = sol[:, 1]
        if fit3rdorder:
            tec3rdarray[itm]=sol[:, 2]
    if returnResiduals:
        if fit3rdorder:
            return (tecarray, clockarray, residualarray,tec3rdarray)
        else:
            return (tecarray, clockarray, residualarray)
    if fit3rdorder:
        return (tecarray, clockarray,tec3rdarray)
    return (tecarray, clockarray)
          

def getPhaseWrapBase(freqs):
    """
    freqs: frequency grid of the data
    return the step size from a local minima (2pi phase wrap) to the others [0]: TEC, [1]: clock
    """

    nF = freqs.shape[0]
    A = np.zeros((nF, 2), dtype=np.float)
    A[:, 1] = freqs * 2 * np.pi * 1e-9
    A[:, 0] = -8.44797245e9 / freqs
    steps = np.dot(np.dot(np.linalg.inv(np.dot(A.T, A)), A.T), 2 * np.pi * np.ones((nF, ), dtype=np.float))
    basef = np.dot(A, steps) - 2 * np.pi
    return (basef, steps)


def getResidualPhaseWraps(avgResiduals, freqs):
    flags = np.average(avgResiduals.mask,axis=1)>0.5
    nSt = avgResiduals.shape[1]
    nF = freqs.shape[0]
    wraps = np.zeros((nSt, ), dtype=np.float)
    tmpflags = flags
    tmpfreqs = freqs[np.logical_not(tmpflags)]
    (tmpbasef, steps) = getPhaseWrapBase(tmpfreqs)
    basef = np.zeros(freqs.shape)
    basef[np.logical_not(tmpflags)] = tmpbasef
    basef = basef.reshape((-1, 1))
    data = avgResiduals[:, :]
    wraps = fitting.fit(data, basef, wraps, flags).flatten()
    return (wraps, steps)


def correctWrapsFromResiduals(residualarray,flags,freq):
    '''corrects solution jumps due to 2 pi phasewraps based on the average residuals'''
    resflags = np.logical_or(flags[:, np.newaxis], residualarray == 0)
    maskedresiduals = np.ma.array(residualarray, mask=resflags)
    # avgResiduals=np.average(residualarray,axis=0)
    avgResiduals = np.ma.average(maskedresiduals, axis=0)
    (wraps, steps) = getResidualPhaseWraps(avgResiduals, freq)  # fitting of the wraps from the time-avg residuals
    # step[0] is the step in TEC corresponding to 1 phase wrap and step[1] is in ns (clock)
    wraps = np.round(wraps - wraps[0])  # reference to station 0
    logging.debug('Wraps from residuals: ' + str(wraps))
    return (wraps, steps)


def correctWraps(
    tecarray,
    residualarray,
    freq,
    pos,
    ):
    '''corrects solution jumps due to 2 pi phasewraps based on spatial correlations of averaged TEC solutions. Also returns average constant phase  offset per station '''
    nT = tecarray.shape[0]
    nSt = tecarray.shape[1]
    flags = tecarray < -5

    (wraps, steps) = correctWrapsFromResiduals(residualarray,flags,freq)
    lats = np.degrees(np.arctan2(pos[:, 2], np.sqrt(pos[:, 0] * pos[:, 0] + pos[:, 1] * pos[:, 1])))
    lats -= lats[0]
    lons = np.degrees(np.arctan2(pos[:, 1], pos[:, 0]))
    lons -= lons[0]
    lonlat = np.concatenate((lons, lats)).reshape((2, ) + lons.shape)
    # refine (is it needed for LBA? check results)
    for nr_iter in xrange(2):
        # recreate best TEC at the moment
        TEC = tecarray - tecarray[:, [0]] + steps[0] * (np.round(wraps) - np.round(wraps[0]))
        TEC = np.ma.array(TEC, mask=flags)
        # fit 2d linear TEC screen over stations
        slope = np.ma.dot(np.linalg.inv(np.dot(lonlat, lonlat.T)), np.ma.dot(lonlat, TEC.T))
        # flag bad time steps maybe because TEC screen is not linear
        chi2 = np.ma.sum(np.square(TEC - np.ma.dot(lonlat.T, slope).T), axis=1) / nSt
        chi2select = chi2 < np.ma.average(chi2)
        chi2select = chi2 < np.ma.average(chi2[chi2select])
        # calculate offset per station wrt time-averaged TEC screen
        offsets = -1 * np.ma.average(TEC[chi2select] - np.ma.dot(slope.T, lonlat)[chi2select], axis=0) * 2. * np.pi / steps[0]
        remainingwraps = np.round(offsets / (2 * np.pi))  # -np.round(wraps[stationIndices])
        logging.debug('Offsets: ' + str(offsets))
        logging.debug('AvgTEC: ' + str(np.ma.average(TEC[chi2select], axis=0)))
        logging.debug('Remaining: ' + str(remainingwraps))
        wraps += remainingwraps
        # TODO: remove also the offset before the second cycle
        if np.sum(np.absolute(remainingwraps)) == 0:
            break
    return (offsets, wraps, steps)


def doFit(
    phases,
    mask,
    freqs,
    stations,
    station_positions,
    axes,
    refstIdx='superterp',
    flagBadChannels=True,
    flagcut=1.5,
    chi2cut=30000.,
    removePhaseWraps=True,
    combine_pol=False,
    fit3rdorder=False,
    circular=False,
    initSol=[],
    initoffsets=[],
    ):
    # make sure order of axes is as expected
    stidx = axes.index('ant')
    freqidx = axes.index('freq')
    timeidx = axes.index('time')
    polidx = axes.index('pol')
    data = ma.array(phases, mask=mask).transpose((timeidx, freqidx, stidx, polidx))
    nT = data.shape[0]
    nF = data.shape[1]
    nSt = data.shape[2]
    npol = data.shape[3]
    if npol == 4:
        data = data[:, :, :, (0, 3)]
        npol = 2
    if refstIdx == 'superterp':
        superterpstations = [i for i in stations if i[:5] in [
            'CS002',
            'CS003',
            'CS004',
            'CS005',
            'CS006',
            'CS007',
            ]]
        refstIdx = [i for (i, j) in enumerate(stations) if j in superterpstations]
    if not hasattr(refstIdx, '__len__'):
        refstIdx = [refstIdx]

    # get phases from reference stations
    refdata = np.ma.sum(np.cos(data[:, :, refstIdx, :]) + 1.j * np.sin(data[:, :, refstIdx, :]), axis=2)
    refdata = np.ma.arctan2(np.imag(refdata), np.real(refdata))
    # unwrap around mean
    mymean = np.ma.average(refdata, axis=0)
    refdata = np.ma.remainder(refdata - mymean[np.newaxis] + np.pi, 2 * np.pi) + mymean[np.newaxis] - np.pi
    data -= refdata[:, :, np.newaxis]
    # flag bad channels - test if really nedded if data already flagged
    indices = np.arange(nF)

    if flagBadChannels:
        mymask=np.zeros((nF), dtype=np.bool)
        for nr_iter in xrange(2):
            rms = np.ma.std(np.ma.std(refdata, axis=0), axis=1)
            freqselect = rms < flagcut * np.average(rms)
            logging.debug('Iter %d: flagging %d channels' % (nr_iter, np.sum(np.logical_not(freqselect))))
            #freqs = freqs[freqselect]
            #data = data[:, freqselect]
            mymask=np.ma.logical_or(mymask,~freqselect)
            #refdata = refdata[:, freqselect]
            refdata.mask=np.ma.logical_or(refdata.mask,mymask[np.newaxis,:,np.newaxis])
            logging.debug('Flagging: ' + str(indices[np.logical_not(freqselect)]))
            #indices = indices[freqselect]
        mask=data.mask
        data.mask=np.logical_or(mask,mymask[np.newaxis,:,np.newaxis,np.newaxis])

    # Remove completely flagged stations
    selectstations = [st for stationIndices, st in enumerate(stations) if data[:, :, stationIndices].mask.all() != True]
    logging.debug('%d selected stations: ' % len(selectstations) + str(selectstations))
    stationIndices = np.array([idxst in selectstations for idxst in stations])
    data = data[:, :, stationIndices]
    stations_old = stations[:] # keep a copy for putting flagged stations back at the end
    stations = stations[stationIndices]

    station_positions = station_positions[stationIndices]
    RSstations = [i for (i, j) in enumerate(stations) if 'RS' in j]
    CSstations = [i for (i, j) in enumerate(stations) if 'CS' in j]
    otherstations = [i for (i, j) in enumerate(stations) if not 'RS' in j and not 'CS' in j]
    logging.debug('Station indices: ' + str(stationIndices) + ' RS ' + str(RSstations))
    nSt = data.shape[2]
    # combine polarizationsif requested - needed in HBA
    if combine_pol:
        if npol == 2 and not circular:
            cdata = np.ma.cos(data) + 1.j * np.ma.sin(data)
            data = np.ma.sum(cdata, axis=3).reshape((nT, nF, nSt, 1))
            data = np.ma.arctan2(np.imag(data), np.real(data))  # np.angle doesnot yet return masked array!!
            npol = 1
        if circular:
            data=np.ma.sum(data, axis=3).reshape((nT, nF, nSt, 1))
            npol=1
    # guess clock, remove from data
    # not in LBA because TEC dominant
    if not 'LBA' in stations[0] and len(initSol) < 1:
        initclock = getInitClock(data[nT / 2:nT / 2 + 100][:, :, RSstations + otherstations], freqs)  # only on a few timestamps
        logging.debug('Initial clocks: ' + str(initclock[1]))
        # init CS clocks to 0
        # logging.debug("data before init clock" + str(data[nT/2,:,-1]))
        data[:, :, RSstations + otherstations] = data[:, :, RSstations + otherstations] - freqs[np.newaxis, :, np.newaxis, np.newaxis] * initclock[1][np.newaxis, np.newaxis, :] * 1e-9 * 2 * np.pi
        # logging.debug("clock correction" + str(np.remainder(freqs*initclock[1][-1]*-1e-9*2*np.pi+np.pi,2*np.pi)-np.pi))
        # logging.debug("data after init clock" + str(np.remainder(data[nT/2,:,-1]+np.pi,2*np.pi)-np.pi))
    offset = np.zeros((nSt, npol), dtype=np.float32)
    if len(initoffsets) > 0:
        offset = initoffsets
        data[:, :, :, :] += offset[:][np.newaxis, np.newaxis]
    # initialize arrays
    clock = np.zeros((nT, nSt, npol), dtype=np.float32)
    tec = np.zeros((nT, nSt, npol), dtype=np.float32)
    if fit3rdorder:
        tec3rd = np.zeros((nT, nSt, npol), dtype=np.float32)
   
    # better not to use fitoffset
    for pol in xrange(npol):
        # get a good guesss without offset
        # logging.debug("sending masked data "+str(data[:,:,:,pol].count()))
        initialchi2cut = chi2cut  # user defined
        if removePhaseWraps:
            initialchi2cut = 30000.  # this number is quite arbitrary
        if fit3rdorder:
            (tecarray, clockarray, residualarray,tec3rdarray) = getClockTECFit(
                np.ma.copy(data[:, :, :, pol]),
                freqs,
                stations,
                initSol=initSol,
                returnResiduals=True,
                fit3rdorder=True,
                chi2cut=initialchi2cut
                )
        else:
            (tecarray, clockarray, residualarray) = getClockTECFit(
                np.ma.copy(data[:, :, :, pol]),
                freqs,
                stations,
                initSol=initSol,
                returnResiduals=True,
                fit3rdorder=False,
                chi2cut=initialchi2cut
                )
        if removePhaseWraps:
            # correctfrist times only,try to make init correct ?
            #corrects wraps based on spatial correlation (averaged in time), only works for long time observations, not testted for LBA
            (offset[:, pol], wraps, steps) = correctWraps(tecarray, residualarray, freqs, station_positions)
        else:
            #always correct for wraps based on average residuals
            wraps, steps = correctWrapsFromResiduals(residualarray, tecarray<-5,freqs)
        logging.debug('Residual iter 1, pol %d: ' % pol + str(residualarray[0, 0]))
        logging.debug('TEC iter 1, pol %d: ' % pol + str(tecarray[0]))
        logging.debug('Clock iter 1, pol %d: ' % pol + str(clockarray[0]))
        logging.debug('Wraps: ' + str(wraps))
        logging.debug('Offsets: ' + str(offset[:, pol]))
        # remove completely initialoffset?
        if len(initoffsets) > 0:
            offset[:, pol] -= initoffsets[:, pol]
        data[:, :, :, pol] += offset[:, pol][np.newaxis, np.newaxis]
        # remove fitoffset
        if removePhaseWraps:
            initsol = np.zeros((nSt, 2), dtype=np.float32)
            initsol[:, 0] = tecarray[0, :] + wraps * steps[0]
            initsol[:, 1] = clockarray[0, :] + wraps * steps[1]
            logging.debug('Initsol TEC, pol %d: ' % pol + str(initsol[:, 0]))
            logging.debug('Initsol clock, pol %d: ' % pol + str(initsol[:, 1]))
            tecarray = 0
            clockarray = 0
            residualarray = 0
            # is it needed to redo the fitting? this is the time bottleneck
            if fit3rdorder:
                (tec[:, :, pol], clock[:, :, pol],tec3rd[:, :, pol]) = getClockTECFit(
                    np.ma.copy(data[:, :, :, pol]),
                    freqs,
                    stations,
                    initSol=initsol,
                    returnResiduals=False,
                    fit3rdorder=True,
                    chi2cut=chi2cut,
                    )
            else:
                (tec[:, :, pol], clock[:, :, pol]) = getClockTECFit(
                    np.ma.copy(data[:, :, :, pol]),
                    freqs,
                    stations,
                    initSol=initsol,
                    returnResiduals=False,
                    fit3rdorder=False,
                    chi2cut=chi2cut,
                    )
        else:
            tec[:, :, pol] = tecarray[:, :]+ wraps * steps[0]
            clock[:, :, pol] = clockarray[:, :]+ wraps * steps[1]
            if fit3rdorder:
              tec3rd[:, :, pol]  = tec3rdarray[:, :]+ wraps * steps[2]
        logging.debug('TEC iter 2, pol %d: ' % pol + str(tec[0, :, pol]))
        logging.debug('Clock iter 2, pol %d: ' % pol + str(clock[0, :, pol]))
    if not 'LBA' in stations[0] and len(initSol) < 1:
        clock[:, RSstations + otherstations] += initclock[1][np.newaxis, :, :]
    if combine_pol and circular:
        clock/=2;tec/=2;offset/=2

    # put flagged stations back
    for idx, wasUsed in enumerate(stationIndices):
        if not wasUsed:
            logging.debug('Adding completely flagged station '+str(idx))
            clock = np.insert(clock,idx,0,axis=1) # [time:ant:pol]
            tec = np.insert(tec,idx,-5,axis=1) # [time:ant:pol]
            offset = np.insert(offset,idx,0,axis=0) # [ant:pol]
            if fit3rdorder: tec3rd = np.insert(tec3rd,idx,0,axis=1) # [time:ant:pol]

#    station = station_old
    if fit3rdorder:
        return (clock, tec, offset, tec3rd)
    else:
        return (clock, tec, offset)
