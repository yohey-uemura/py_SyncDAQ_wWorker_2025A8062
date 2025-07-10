#! /usr/bin/env /home/uemura/Apps/anaconda3_2021Aprl/bin/python3

#$ -N getMPCCD_pp.py
#$ -l mem=50G
#$ -o /work/uemura/qsub_outs/
#$ -e /work/uemura/qsub_outs/


from math import sqrt
from joblib import Parallel, delayed
import numpy as np
import pandas as pd
import sys, h5py, os, re, tqdm, io, glob, csv, argparse, yaml, time
from yaml.loader import SafeLoader
import numexpr as nexpr
from operator import itemgetter
from itertools import zip_longest
import ipywidgets as widgets
from tqdm import tqdm

############### The following part should be changed for each beamtime ###############

darkimage = np.load('/home/uemura/python/py_SyncDAQ_wWorker_2025A8062_beta/mpccd_dark.npy')
roi_x = [520,660]
roi_y = [30,320]
lowcut = 65

detName = 'MPCCD-1B1-M03-004'
BL = 3
xshutter = 1
# pythondir = '/home/uemura/Apps/anaconda3_2021Aprl/bin'
# confdir = '/home/uemura/python/jupyter_notebook/2022June_2022A8069/syncDAQ/Event_Conf'
"""
You have to modify the following line
"""
_outdir = '/work/uemura/test_2022A8063'

###########################################################################################

if 'xhpcfep' in os.uname().nodename:
    sys.exit('You cannot use this script from a node of "xhpcfep"s.\nLog in "hpc"-nodes using "qsub -I -X"')
import yaml
import time
import re
import subprocess as sub
import dbpy, stpy
import tifffile as tif


def getMPCCD_roi(runnumber, nth, _tagnumbers, sufix, ROIs, THR, prefix='/work/uemura/test_2022A8063',tagskip=1):
    if not os.path.isdir(f'{prefix}/r{runnumber}'):
        os.mkdir(f'{prefix}/r{runnumber}')
    outdir = f'{prefix}/r{runnumber}'
    print (f"{detName}, {BL}, {runnumber}")
    s = stpy.StorageReader(detName,BL,tuple([runnumber]))
    buffer = stpy.StorageBuffer(s)
    print("######start runnumber: "+str(runnumber)+","+"split: {:d}".format(nth)+"#####")
    START = time.time()
    # mpccd=pd.DataFrame(index=_tagnumbers,columns=['data'])
    arr_mpccd = []
    mpccd_couts = []
    for tag in tqdm(_tagnumbers):
        s.collect(buffer,tag)
        mpccd_data = buffer.read_det_data(0)
        mpccd_data -= darkimage
        arr_mpccd.append(mpccd_data)
        sub = mpccd_data[ROIs[0]:ROIs[1],ROIs[2]:ROIs[3]]
        mpccd_couts.append(sub.sum(where=(sub>THR[0])*(sub<THR[1])))
    if os.path.isfile(outdir+'/'+'run_{:d}_mpccd_{:02d}_{:s}.h5'.format(runnumber,nth,sufix)):
        os.remove(outdir+'/'+'run_{:d}_mpccd_{:02d}_{:s}.h5'.format(runnumber,nth,sufix))
    h5f = h5py.File(outdir+'/'+'run_{:d}_mpccd_{:02d}_{:s}.h5'.format(runnumber,nth,sufix),'w')
    h5f.create_group('run_{:d}'.format(runnumber))
    h5f.create_dataset('run_{:d}/mpccd'.format(runnumber),data=np.array(arr_mpccd))
    h5f.create_dataset('run_{:d}/counts'.format(runnumber), data=np.array(mpccd_couts))
    h5f.create_dataset('run_{:d}/tags'.format(runnumber),data=_tagnumbers)
    h5f.flush()
    h5f.close()
#     if os.path.isfile(outdir+'/'+f'run_{runnumber}_mpccd_{nth:02d}.ph5'):
#         os.remove(outdir+'/'+f'run_{runnumber}_mpccd_{nth:02d}.ph5')
#     mpccd.to_hdf(outdir+'/'+f'run_{runnumber}_mpccd_{nth:02d}.ph5',key='mpccd',mode='w')
    
    print("######end runnumber: "+str(runnumber)+","+"split: {:d}".format(nth)+" ({:.1f} s)#####".format(time.time()-START))

if __name__=='__main__':
    runnumber = int(os.environ['RUN'])
    nth = int(os.environ['SPLIT'])
    str_tags = os.environ['TAGS']
    tagnumbers = np.array(eval(str_tags.replace(':',','))).astype(int)
    outdir=os.environ['OUTDIR']
    sufix=os.environ['SUFIX']
    str_rois = os.environ['ROIS']
    ROIs = [int(x) for x in str_rois.split(':')]
    thr = os.environ['THR']
    thr = [float (x) for x in thr.split(':')]
    for name, value in os.environ.items():
        print("{0}: {1}".format(name, value))
    # print (runnumber, nth,outdir)
    getMPCCD_roi(runnumber, nth, tagnumbers,sufix,ROIs,thr,outdir)
    # tagnumbers = np.array(eval(args.tags.replace(':',','))).astype(int)