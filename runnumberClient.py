import sys, os, string, io, glob, re, yaml, math, time, shutil, queue, natsort
from itertools import count

import h5py
import numpy as np
import pandas as pd
import subprocess as sub
from silx.gui.qt import QObject, QThread, QTimer, pyqtSignal as Signal, pyqtSlot as Slot
from joblib import Parallel, delayed
from tqdm import tqdm
from tqdm.tk import tqdm as tqdm_tk

try:
    import dbpy
    import stpy
except:
    print ('Failed to load dbpy/stpy')
    sys.exit()

class Worker(QThread):
    data_queued = Signal()
    echo_rnum = Signal(int)

    def __init__(self, BL, stop_after=0, parent=None):
        super().__init__(parent)
        self.BL = BL
        self.stop_after = stop_after
        self.process = 1
        self.paused = True

    def run(self):
        while self.process:
            if not self.paused:
                _runnumber = dbpy.read_runnumber_newest(self.BL)
                self.echo_rnum.emit(_runnumber)
            time.sleep(5)


class syncDAQ(QThread):
    process_end = Signal(float)
    nsplit = 5

    def __init__(self, BL, rnum, confdir, outpath, devlist,
                 use_mpccd, mpccd, bgfile,
                 roi_x_ll, roi_y_ll, roi_x_ul, roi_y_ul,
                 c_ll, c_ul,parent=None):
        super().__init__(parent)
        self.BL = BL
        self.rnum = rnum
        self.confdir = confdir
        self.outpath = outpath
        self.devlist = devlist
        self.use_mpccd = use_mpccd
        self.mpccd = mpccd
        self.bgfile = bgfile
        self.roi_x_ll = int(roi_x_ll)
        self.roi_y_ll = int(roi_y_ll)
        self.roi_x_ul = int(roi_x_ul)
        self.roi_y_ul = int(roi_y_ul)
        self.c_ll = c_ll
        self.c_ul = c_ul


    def getMPCCD(self, runnumber, device_id,tagnumbers,bgdata,
                 roi_x_ll, roi_y_ll, roi_x_ul, roi_y_ul,c_ll, c_ul):
        print("######start runnumber: " + str(runnumber) + "#####")
        print (f'device_id: {device_id}')
        s = stpy.StorageReader(device_id, 3, tuple([runnumber]))
        buffer = stpy.StorageBuffer(s)
        # START = time.time()
        dfmpccd = pd.DataFrame(index=tagnumbers,columns=['count'])
        for tag in tqdm(tagnumbers):
            s.collect(buffer, tag)
            img = (buffer.read_det_data(0) - bgdata)[roi_x_ll:roi_x_ul,roi_y_ll:roi_y_ul]
            dfmpccd['count'][tag] = img.sum(where=(img > c_ll)*(img < c_ul))
        return dfmpccd['count'].values

            # dfmpccd[str(runnumber) + ':' + str(tagnumbers[i])] = buffer.read_det_data(0)

        # h5f = h5py.File(mpccddir + '/' + 'run_' + str(runnumber) + '.h5', 'w')
        # for i in range(len(tagnumbers)):
        #     h5f.create_dataset('tag_' + str(tagnumbers[i]), data=dfmpccd[str(runnumber) + ':' + str(tagnumbers[i])])
        # h5f.flush()
        # h5f.close()

    def run(self):
        try:
            stime = time.time()
            taglist_all = []
            filterlist = self.confdir + '/' + 'FEL_openshutter_beamon.txt'
            args = ['MakeTagList', '-r', str(self.rnum), '-b', str(self.BL), '-inp', filterlist]
            P_MkTagList = sub.Popen(args, stdout=sub.PIPE)
            stdout, stderror = P_MkTagList.communicate()
            for term in io.StringIO(stdout.decode('utf-8')):
                if re.match(r'^\d+$', term.rstrip()):
                    taglist_all.append(int(term.rstrip()))
            taglist_laseron = []
            filterlist = self.confdir + '/' + 'FEL_LH1_openshutter_beamon.txt'
            args = ['MakeTagList', '-r', str(self.rnum), '-b', str(self.BL), '-inp', filterlist]
            P_MkTagList = sub.Popen(args, stdout=sub.PIPE)
            stdout, stderror = P_MkTagList.communicate()
            for term in io.StringIO(stdout.decode('utf-8')):
                if re.match(r'^\d+$', term.rstrip()):
                    taglist_laseron.append(int(term.rstrip()))

            taglist_laseroff = [x for x in taglist_all if not x in taglist_laseron]

            taghi = dbpy.read_hightagnumber(self.BL, self.rnum)

            motors = [d for d in self.devlist if 'xfel_bl_3_st_2_motor' in d]
            pds = [d for d in self.devlist if 'xfel_bl_3_st_2_pd_user' in d]

            if taglist_laseron and taglist_laseroff:
                for z, _taglist in enumerate([taglist_laseron, taglist_laseroff]):
                    out = Parallel(n_jobs=5, backend='threading')(
                        delayed(dbpy.read_syncdatalist)(d, taghi, tuple(_taglist)) for d in self.devlist)

                    df = {}
                    df['#Tag'] = np.array([str(tag) for tag in _taglist])
                    df['mono'] = np.array(out[0])
                    for k, _motor in enumerate(motors):
                        df[_motor.replace('xfel_bl_3_st_2_','').replace('/position','')] = np.array(out[1+k])
                    nums_pds = ['pd_' + term.replace('xfel_bl_3_st_2_pd_user_', '').replace('_fitting_peak/voltage', '') for term in self.devlist[len(motors)+1:-1]]
                    for i, label in enumerate(nums_pds):
                        df[label] = np.array(out[len(motors)+1 + i])
                    ONOFF = 'laseron' * (z == 0) + 'laseroff' * (z == 1)
                    df['laser_pd'] = np.array(out[-1])

                    if self.use_mpccd:
                        job_ids = []
                        job_errs = []
                        df_pbs = pd.DataFrame(
                            index=[f'job: {x:02d}' for x in range(int(self.nsplit))],
                            columns=['stdout', 'stderr']
                        )

                        arrs = np.array_split(np.array(_taglist), self.nsplit)
                        print(f">>> Job submission: {ONOFF}")
                        for i, _a in enumerate(arrs):
                            str_arr = '[' + ':'.join([str(x) for x in _a.astype(int)]) + ']'
                            str_pars = f'RUN={self.rnum},SPLIT={i},TAGS={str_arr},' + f'OUTDIR={self.outpath},SUFIX={ONOFF},'
                            str_pars += f'ROIS={self.roi_x_ll}:{self.roi_x_ul}:{self.roi_y_ll}:{self.roi_y_ul},'
                            str_pars += f'THR={self.c_ll}:{self.c_ul}'
                            args = ['qsub', '-v', str_pars, '-l mem=30G', '-o /work/uemura/qsub_outs/',
                                    '-e /work/uemura/qsub_outs/', 'getMPCCD_pp.py']
                            pbs_getMPCCD = sub.Popen(args, stdout=sub.PIPE, stderr=sub.PIPE)
                            _data, _err = pbs_getMPCCD.communicate()
                            job_ids.append(_data.decode('utf-8').rstrip())
                            job_errs.append(_err.decode('utf-8').rstrip())

                        df_pbs['stdout'] = job_ids
                        df_pbs['stderr'] = job_errs
                        if all([('fep' in x) for x in job_ids]):
                            print(">>> The job submission succeeded (^o^)/ <<<")

                            """
                            Check job status
                            """
                            job_status = []
                            for _job in job_ids:
                                args = ['qstat', _job]
                                qstat = sub.Popen(args, stdout=sub.PIPE, stderr=sub.PIPE)
                                stdout, stderr = qstat.communicate()
                                # print(stdout, stderr)
                                if 'finished' in stderr.decode('utf-8').rstrip():
                                    job_status.append(True)
                                else:
                                    job_status.append(False)

                            while not (all(job_status)):
                                time.sleep(5)
                                job_status = []
                                for _job in job_ids:
                                    args = ['qstat', _job]
                                    qstat = sub.Popen(args, stdout=sub.PIPE, stderr=sub.PIPE)
                                    stdout, stderr = qstat.communicate()
                                    # print(stdout, stderr)
                                    if 'finished' in stderr.decode('utf-8').rstrip():
                                        job_status.append(True)
                                    else:
                                        job_status.append(False)

                            hdffiles = [x for x in os.listdir(self.outpath + f'/r{self.rnum}') if re.match(f'run_{self.rnum}_mpccd_\d\d_{ONOFF}\.h5', x)]
                            if len(hdffiles) == self.nsplit:
                                print("  >>> MPCCD was processed properly <<<")
                                arr_counts = np.array([])
                                arr_tags = np.array([])
                                outdir = self.outpath+f'/r{self.rnum}'
                                for f in natsort.natsorted(hdffiles):
                                    h5 = h5py.File(outdir+'/'+f)
                                    arr_counts = np.append(arr_counts,h5[f'run_{self.rnum}/counts'][:])
                                    arr_tags = np.append(arr_counts, h5[f'run_{self.rnum}/tags'][:])
                                df['mpccd'] = arr_counts
                            else:
                                print("!! hdf5 files are not created properly...")
                                pass

                        else:
                            print(">>> The job submission faild (ToT) <<<")

                    pd.DataFrame(df).to_csv(self.outpath + '/' + f"r{self.rnum}" + '/' + f'{ONOFF}_r{self.rnum}.csv',index=False)



            else:
                out = Parallel(n_jobs=8, backend='threading')(
                    delayed(dbpy.read_syncdatalist)(d, taghi, tuple(taglist_all)) for d in self.devlist)
                df = {}
                df['#Tag'] = np.array([str(tag) for tag in taglist_all])
                df['mono'] = np.array(out[0])
                for k, _motor in enumerate(motors):
                    df[_motor.replace('xfel_bl_3_st_2_', '').replace('/position','')] = np.array(out[1 + k])
                nums_pds = ['pd_' + term.replace('xfel_bl_3_st_2_pd_user_', '').replace('_fitting_peak/voltage', '') for term in self.devlist[len(motors) + 1:-1]]
                for i, label in enumerate(nums_pds):
                    df[label] = np.array(out[len(motors) + 1 + i])
                df['laser_pd'] =  np.array(out[-1])

                if self.use_mpccd:
                    job_ids = []
                    job_errs = []
                    df_pbs = pd.DataFrame(
                        index=[f'job: {x:02d}' for x in range(int(self.nsplit * 2))],
                        columns=['stdout', 'stderr']
                    )

                    arrs = np.array_split(np.array(taglist_all), int(self.nsplit*2))
                    for i, _a in enumerate(arrs):
                        str_arr = '[' + ':'.join([str(x) for x in _a.astype(int)]) + ']'
                        str_pars = f'RUN={self.rnum},SPLIT={i},TAGS={str_arr},' + f'OUTDIR={self.outpath},SUFIX=all,'
                        str_pars += f'ROIS={self.roi_x_ll}:{self.roi_x_ul}:{self.roi_y_ll}:{self.roi_y_ul},'
                        str_pars += f'THR={self.c_ll}:{self.c_ul}'
                        args = ['qsub', '-v', str_pars, '-l mem=30G', '-o /work/uemura/qsub_outs/',
                                '-e /work/uemura/qsub_outs/', 'getMPCCD_pp.py']
                        pbs_getMPCCD = sub.Popen(args, stdout=sub.PIPE, stderr=sub.PIPE)
                        _data, _err = pbs_getMPCCD.communicate()
                        job_ids.append(_data.decode('utf-8').rstrip())
                        job_errs.append(_err.decode('utf-8').rstrip())

                    df_pbs['stdout'] = job_ids
                    df_pbs['stderr'] = job_errs
                    if all([('fep' in x) for x in job_ids]):
                        print(">>> The job submission succeeded (^o^)/ <<<")

                        """
                        Check job status
                        """
                        job_status = []
                        for _job in job_ids:
                            args = ['qstat', _job]
                            qstat = sub.Popen(args, stdout=sub.PIPE, stderr=sub.PIPE)
                            stdout, stderr = qstat.communicate()
                            # print(stdout, stderr)
                            if 'finished' in stderr.decode('utf-8').rstrip():
                                job_status.append(True)
                            else:
                                job_status.append(False)

                        while not (all(job_status)):
                            time.sleep(5)
                            job_status = []
                            for _job in job_ids:
                                args = ['qstat', _job]
                                qstat = sub.Popen(args, stdout=sub.PIPE, stderr=sub.PIPE)
                                stdout, stderr = qstat.communicate()
                                # print(stdout, stderr)
                                if 'finished' in stderr.decode('utf-8').rstrip():
                                    job_status.append(True)
                                else:
                                    job_status.append(False)

                        hdffiles = [x for x in os.listdir(self.outpath + f'/r{self.rnum}') if
                                    re.match(f'run_{self.rnum}_mpccd_\d\d_{ONOFF}\.h5', x)]
                        if len(hdffiles) == self.nsplit:
                            arr_counts = np.array([])
                            arr_tags = np.array([])
                            outdir = self.outpath + f'/r{self.rnum}'
                            for f in natsort.natsorted(hdffiles):
                                h5 = h5py.File(outdir + '/' + f)
                                arr_counts = np.append(arr_counts, h5[f'run_{self.rnum}/counts'][:])
                                arr_tags = np.append(arr_counts, h5[f'run_{self.rnum}/tags'][:])
                            df['mpccd'] = arr_counts
                        else:
                            print("!! hdf5 files are not created properly...")
                            pass

                    else:
                        print(">>> The job submission faild (ToT) <<<")

                pd.DataFrame(df).to_csv(self.outpath + '/' + f"r{self.rnum}" + '/' + f'laserall_r{self.rnum}.csv',index=False)

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            linenumber = exc_tb.tb_lineno
            print(f'Line {linenumber}: {str(e)}')

        self.process_end.emit(time.time() - stime)

class QBridgeClient(QObject):
    worker = None
    syncdaq = None
    _dequeuing = False
    stopped = Signal()
    new_runnumber = Signal(int,str)
    _msg = Signal(str)

    new_data = Signal(list,list,list)
    HOMEDIR = os.environ['HOME']
    PYDIR = HOMEDIR+'/python'
    PROGRAMDIR = PYDIR+'/py_SyncDAQ_wWorker_2025A8062_dev'
    confdir = PROGRAMDIR+'/Event_Conf'


    def __init__(self, BL, rstart, r_end, devlist = [], outpath = None, use_mpccd=False, mpccd_id=None, bgfile=None,
                 roi_x_ll=None, roi_y_ll=None, roi_x_ul=None, roi_y_ul=None,c_ll=None,c_ul=None,
                 parent=None):
        super().__init__(parent)
        self.BL = BL
        self.rstart = self.runnumber = rstart
        self.r_end = r_end
        self.devlist = devlist
        self.new_data = Signal(list, list, list)
        self.outpath = outpath
        self.use_mpccd = use_mpccd
        self.mpccd_id = mpccd_id
        self.bgfile = bgfile
        self.roi_x_ll = roi_x_ll
        self.roi_y_ll = roi_y_ll
        self.roi_x_ul = roi_x_ul
        self.roi_y_ul = roi_y_ul
        self.c_ll = c_ll
        self.c_ul = c_ul


    def setMPCCD(self,use_mpccd,mpccd_id,bgfile,roi_x_ll,roi_x_ul,roi_y_ll,roi_y_ul,c_ll,c_ul):
        self.use_mpccd = use_mpccd
        self.mpccd_id = mpccd_id
        self.bgfile = bgfile
        self.roi_x_ll = roi_x_ll
        self.roi_x_ul = roi_x_ul
        self.roi_y_ll = roi_y_ll
        self.roi_y_ul = roi_y_ul
        self.c_ll = c_ll
        self.c_ul = c_ul
        txt = '>>>>> MPCCD is Enabled <<<<<'
        txt += f'\n- Device ID: {self.mpccd_id}'
        txt += f'\n- Back ground: {self.bgfile}'
        txt += f'\n- roi_x: [{self.roi_x_ll},{self.roi_x_ul}]'
        txt += f'\n- roi_y: [{self.roi_y_ll},{self.roi_y_ul}]'
        self._msg.emit(txt)


    def set_endpoint(self, rstart, r_end, devlist,outpath):
        self.rstart = self.runnumber = rstart
        self.r_end = r_end
        self.devlist = devlist
        self.outpath = outpath

    def start(self, stop_after=0):
        print ("Start Client")
        print (self.outpath)
        """Start receiving data

        Connect to the ``new_data`` signal to handle incoming data.

        If stop_after > 0, it will automatically stop once N trains have been
        received. Otherwise, it continues until ``.stop()`` is called.
        """
        if self.worker is not None:
            raise RuntimeError("Client is already running")

        self.worker = worker = Worker(
            self.BL,stop_after=stop_after, parent=self,
        )
        worker.echo_rnum.connect(self._dequeue_one)
        worker.finished.connect(self._worker_finished)
        self.worker.paused = False
        worker.start()

    @property
    def is_active(self):
        if self.worker is not None:
            print ("Worker is running")
            return 1
        else:
            return 0

    def set_new_runnumber(self,t_process):
        self.runnumber += 1
        self.new_runnumber.emit(self.runnumber,f"     ########## process ends: {t_process:.1f} s ###########")
        # self._msg.emit(f"     ########## process ends: {t_process:.1f} s ###########")

    def reset_worker(self):
        self.syncdaq = None
        if self.worker:
            self.worker.paused = False

    def _dequeue_one(self, rnum):
        #print(rnum)
        if rnum > self.runnumber and self.runnumber <= self.r_end:
            if self.syncdaq is None:
                self.worker.paused = True
                self._msg.emit('ready to convert run' + str(self.runnumber) + '...')
                print(f">>>>> Make Taglist run:{self.runnumber}<<<<<")
                self._msg.emit(f"     >>>>> Make Taglist run:{self.runnumber}<<<<<")
                try:
                    if not os.path.isdir(self.outpath + '/' + f"r{self.runnumber}"):
                        os.mkdir(self.outpath + '/' + f'r{self.runnumber}')

                    self.syncdaq = syncDAQ(self.BL, self.runnumber, self.confdir, self.outpath, self.devlist,
                                           self.use_mpccd,self.mpccd_id,self.bgfile,
                                           self.roi_x_ll,self.roi_y_ll,self.roi_x_ul,self.roi_y_ul,
                                           self.c_ll,self.c_ul,
                                           parent=self)
                    self.syncdaq.process_end.connect(self.set_new_runnumber)
                    self.syncdaq.finished.connect(self.reset_worker)
                    self._msg.emit(f"     >>>>> take data from the server <<<<<")
                    self.syncdaq.start()
                    # print (taglist_all)
                    # self.new_data.emit(taglist_all,taglist_laseron,taglist_laseroff)
                except Exception as e:
                    print(e)
                    return
        elif rnum >= self.runnumber and self.runnumber <= self.r_end:
            print(f" >>>>> The runnumber={self.runnumber} is not ready <<<<<")
        else:
            print(f" >>>>> The runnumber={self.runnumber} exceeds the maximum<<<<<")
            self.new_runnumber.emit(self.runnumber, '')
            self.stop()

    def stop(self):
        """Stop receiving data"""
        if self.worker is None:
            return
        else:
            self.worker.process = 0

    def _worker_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.stopped.emit()
