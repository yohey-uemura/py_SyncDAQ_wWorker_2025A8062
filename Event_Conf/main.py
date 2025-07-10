#!/usr/bin/env /home/uemura/Apps/anaconda3_2021Aprl/bin/python
import sys, os, string, io, glob, re, yaml, math, time, shutil
import numpy as np
import pandas as pd

import matplotlib.pyplot as plt

# import silx
from silx.gui import qt
app = qt.QApplication([])

# from silx.gui.plot import PlotWindow, Plot1D, Plot2D, PlotWidget,items
# import silx.gui.colors as silxcolors
# import silx.io as silxIO

def CC2Eng(M):
    theta = M*4/10**6
    return 12.3984/(6.270832*np.sin(theta*np.pi/180.0))*1000

from mw import Ui_MainWindow
from runnumberClient import QBridgeClient

def msg(txt):
    _msg = qt.QMessageBox()
    _msg.setIcon(qt.QMessageBox.Warning)
    _msg.setText(txt)
    _msg.setStandardButtons(qt.QMessageBox.Ok)
    return _msg.exec_()


class MainWindow(qt.QMainWindow):

    HOMEDIR = os.environ['HOME']
    PYDIR = HOMEDIR+'/python'
    PROGRAMDIR = PYDIR+'/py_SyncDAQ_wWorker_2025A8062_beta'
    confdir = PROGRAMDIR+'/Event_Conf'

    def __init__(self):
        super(MainWindow, self).__init__()
        self.u = Ui_MainWindow()
        self.u.setupUi(self)

        # self.motorlist = yaml.load(open(self.PROGRAMDIR+'/motorlist.yaml'),Loader=yaml.Loader)['eqid']
        self.set_motors()

        ############ Plotters ############

        self.fig, self.ax = plt.subplots(1,2,figsize=(8,4))
        self.ax2 = self.ax[0].twinx()
        self.ax3 = self.ax[1].twinx()

        def chooseDatDir():
            _dir = self.u.textBrowser.toPlainText()
            self.u.textBrowser.clear()
            basedir = self.HOMEDIR
            if os.path.isdir(_dir):
                basedir = _dir

            datdir = qt.QFileDialog.getExistingDirectory(None, 'Select a folder:',
                                                            basedir, qt.QFileDialog.ShowDirsOnly)
            self.u.textBrowser.append(datdir.rstrip())

        self.u.pB_path.clicked.connect(chooseDatDir)
        self.u.sB_RN_start.valueChanged[int].connect(self.u.sB_RN_end.setMinimum)
        self.u.sB_RN_start.valueChanged[int].connect(self.u.progressBar.setMinimum)
        self.u.sB_RN_start.valueChanged[int].connect(self.u.progressBar.setValue)
        self.u.sB_RN_end.valueChanged[int].connect(self.u.progressBar.setMaximum)

        self.show()
        run_start, run_end = self.u.sB_RN_start.value(), self.u.sB_RN_end.value()
        self.current_rnum = self.u.sB_RN_start.value()
        device_list = ['xfel_bl_3_st_1_motor_3/position']
        device_list += [ self.motorlist[self.u.listWidget.item(n).text()] +'/position' for n in range(self.u.listWidget.count()) if self.u.listWidget.item(n).isSelected()]
        device_list += [f'xfel_bl_3_st_2_pd_user_{j}_fitting_peak/voltage' for j in range(1,16) if getattr(self.u,f"pdI0_{j}").isChecked()]+\
                       [f'xfel_bl_3_st_2_pd_user_{j}_fitting_peak/voltage' for j in range(1, 16) if getattr(self.u, f"pdI_{j}").isChecked()]
        device_list += [self.laser_pd]
        self.num_pdlist = [ j for j in range(1,16) if getattr(self.u,f"pdI0_{j}").isChecked()]+ \
                                  [j for j in range(1, 16) if getattr(self.u, f"pdI_{j}").isChecked()]
        self.client = QBridgeClient(3, run_start,run_end,device_list,self.PROGRAMDIR,parent=self)
        self.u.pB_run.clicked.connect(self.start_stop_client)
        self.client.stopped.connect(self.toggle_button)
        self.client.new_runnumber.connect(self.update_runnumber)
        self.client._msg.connect(self.u.textBrowser_2.append)
        self.u.pushButton.clicked.connect(self.set_motors)

    def set_motors(self):
        self.motorlist = yaml.load(open(self.PROGRAMDIR + '/motorlist.yaml'), Loader=yaml.Loader)['eqid']
        self.laser_pd = yaml.load(open(self.PROGRAMDIR + '/motorlist.yaml'), Loader=yaml.Loader)['laser']['pd']
        self.u.listWidget.clear()
        self.u.listWidget.addItems(self.motorlist.keys())
        for idx in range(self.u.listWidget.count()):
            self.u.listWidget.item(idx).setSelected(True)

        try:
            self.mpccd_id = yaml.load(open(self.PROGRAMDIR + '/motorlist.yaml'), Loader=yaml.Loader)['mpccd']['id']
            self.u.lineEdit_2.setText(self.mpccd_id)

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            linenumber = exc_tb.tb_lineno
            msg(f'Line {linenumber}: {str(e)}')
            pass

    def toggle_button(self):
        if self.u.pB_run.isChecked():
            self.u.pB_run.toggle()

    def update_runnumber(self,value,_msg):
        try:
            if self.current_rnum < value:
                self.u.textBrowser_2.append(_msg)
                stime = time.time()
                self.u.progressBar.setValue(self.current_rnum)
                self.u.lcdNumber.display(self.current_rnum)
                motors = [self.motorlist[self.u.listWidget.item(n).text()]  for n in range(self.u.listWidget.count()) if self.u.listWidget.item(n).isSelected()]

                ###### Post processing #####
                sI0_1, sI0_2, sIf = f'pd_{self.num_pdlist[0]}', f'pd_{self.num_pdlist[1]}', f'pd_{self.num_pdlist[2]}'
                I0_ll, I0_ul, If_ll, If_ul = self.u.dsb_I0_ll.value(), self.u.dsb_I0_ul.value(), self.u.dsb_If_ll.value(), self.u.dsb_If_ul.value()
                label = 'laser_pd'

                self.path_to_data = self.u.textBrowser.toPlainText()+'/'+f'r{self.current_rnum}'
                if os.path.isfile(self.path_to_data+'/'+f'laseron_r{self.current_rnum}.csv') and os.path.isfile(self.path_to_data+'/'+f'laseroff_r{self.current_rnum}.csv'):
                    self.u.textBrowser_2.append("     >>>>>>>>>> Post processing <<<<<<<<<<")
                    self.u.textBrowser_2.append('     ########## Laser Off ##########')
                    df = pd.read_csv(self.path_to_data + '/' +  f'laseroff_r{self.current_rnum}.csv')

                    _df = {
                        'Tag': [],
                        'mono': [],
                        sI0_1: [],
                        sI0_2: [],
                        sIf: [],
                    }
                    for _m in motors:
                        _df[_m.replace('xfel_bl_3_st_2_','')] = []
                    if self.u.checkBox.isCheckable():
                        _df['mpccd'] = []
                    for i, tag in enumerate(df['#Tag'].values):
                        _df['Tag'].append(tag)
                        _df['mono'].append(int(df['mono'].values[i].replace('pulse', '')))
                        for _m in motors:
                            _df[_m.replace('xfel_bl_3_st_2_', '')].append(int(df[_m.replace('xfel_bl_3_st_2_', '')].values[i].replace('pulse', '')))

                        ######### pd: I0_1 ##########
                        if ('not-converged' in df[sI0_1].values[i]) or ('saturated' in df[sI0_1].values[i]):
                            _df[sI0_1].append(np.nan)
                        else:
                            _df[sI0_1].append(float(df[sI0_1].values[i].replace('V', '')))

                        ######### pd: I0_2 ##########
                        if ('not-converged' in df[sI0_2].values[i]) or ('saturated' in df[sI0_2].values[i]):
                            _df[sI0_2].append(np.nan)
                        else:
                            _df[sI0_2].append(float(df[sI0_2].values[i].replace('V', '')))

                        ######### pd: If ##########
                        if ('not-converged' in df[sIf].values[i]) or ('saturated' in df[sIf].values[i]):
                            _df[sIf].append(np.nan)
                        else:
                            _df[sIf].append(float(df[sIf].values[i].replace('V', '')))

                        ######## mpccd ##########
                        if self.u.checkBox.isCheckable():
                            if (df[sI0_1].values[i] in ['not-converged', 'saturated']) or (df[sI0_2].values[i] in ['not-converged', 'saturated']):
                                _df['mpccd'].append(np.nan)
                            else:
                                _df['mpccd'].append(df['mpccd'].values[i])

                        ######### pd: laser ########
                        _df[label] = []
                        if ('not-converged' in df[label].values[i]) or ('saturated' in df[label].values[i]):
                            _df[label].append(np.nan)
                        else:
                            _df[label].append(float(df[label].values[i].replace('V', '')))

                    dfout = {
                            'mono': np.array(_df['mono']),
                            'I0': (np.array(_df[sI0_1]) + np.array(_df[sI0_2]))/2,
                            'If': np.array(_df[sIf])
                        }
                    dfout[label] = _df[label]
                    if self.u.checkBox.isCheckable():
                        dfout['mpccd'] = _df['mpccd']

                    for _m in motors:
                        dfout[_m.replace('xfel_bl_3_st_2_','')] = np.array(_df[_m.replace('xfel_bl_3_st_2_','')])

                    data_off = pd.DataFrame(
                        dfout,
                        index=_df['Tag']
                    )
                    data_off.to_hdf(self.path_to_data + '/' + f'laseroff_r{self.current_rnum}.ph5',key = 'data')

                    self.u.textBrowser_2.append('     ########## Laser On ##########')
                    df = pd.read_csv(self.path_to_data + '/' + f'laseron_r{self.current_rnum}.csv')

                    _df = {
                        'Tag': [],
                        'mono': [],
                        sI0_1: [],
                        sI0_2: [],
                        sIf: [],
                    }

                    for _m in motors:
                        _df[_m.replace('xfel_bl_3_st_2_', '')] = []

                    if self.u.checkBox.isCheckable():
                        _df['mpccd'] = []
                    for i, tag in enumerate(df['#Tag'].values):
                        _df['Tag'].append(tag)
                        _df['mono'].append(int(df['mono'].values[i].replace('pulse', '')))
                        for _m in motors:
                            _df[_m.replace('xfel_bl_3_st_2_', '')].append(
                                int(df[_m.replace('xfel_bl_3_st_2_', '')].values[i].replace('pulse', '')))

                        ######### pd: I0_1 ##########
                        if ('not-converged' in df[sI0_1].values[i]) or ('saturated' in df[sI0_1].values[i]):
                            _df[sI0_1].append(np.nan)
                        else:
                            _df[sI0_1].append(float(df[sI0_1].values[i].replace('V', '')))

                        ######### pd: I0_2 ##########
                        if ('not-converged' in df[sI0_2].values[i]) or ('saturated' in df[sI0_2].values[i]):
                            _df[sI0_2].append(np.nan)
                        else:
                            _df[sI0_2].append(float(df[sI0_2].values[i].replace('V', '')))

                        ######### pd: If ##########
                        if ('not-converged' in df[sIf].values[i]) or ('saturated' in df[sIf].values[i]):
                            _df[sIf].append(np.nan)
                        else:
                            _df[sIf].append(float(df[sIf].values[i].replace('V', '')))

                        ######## mpccd ##########
                        if self.u.checkBox.isCheckable():
                            if (df[sI0_1].values[i] in ['not-converged', 'saturated']) or (df[sI0_2].values[i] in ['not-converged', 'saturated']):
                                _df['mpccd'].append(np.nan)
                            else:
                                _df['mpccd'].append(df['mpccd'].values[i])

                        ######### pd: laser ########
                        _df[label] = []
                        if ('not-converged' in df[label].values[i]) or ('saturated' in df[label].values[i]):
                            _df[label].append(np.nan)
                        else:
                            _df[label].append(float(df[label].values[i].replace('V', '')))

                    dfout = {
                        'mono': np.array(_df['mono']),
                        'I0': (np.array(_df[sI0_1]) + np.array(_df[sI0_2])) / 2,
                        'If': np.array(_df[sIf])
                    }
                    dfout[label] = _df[label]
                    if self.u.checkBox.isCheckable():
                        dfout['mpccd'] = _df['mpccd']

                    for _m in motors:
                        dfout[_m.replace('xfel_bl_3_st_2_', '')] = np.array(_df[_m.replace('xfel_bl_3_st_2_', '')])

                    data_on = pd.DataFrame(
                        dfout,
                        index=_df['Tag']
                    )
                    data_on.to_hdf(self.path_to_data + '/' + f'laseron_r{self.current_rnum}.ph5',key = 'data')

                    monos = np.unique(data_on['mono'].values)
                    motor_values = np.array([np.unique(data_on[_m.replace('xfel_bl_3_st_2_', '')].values) for _m in motors])
                    len_motor_values = np.array([arr.size for arr in motor_values])

                    xas_on, xas_off, err_on, err_off = [], [], [], []
                    I0_on, I0_off, If_on, If_off, shots_on, shots_off = [], [], [], [], [], []
                    laser_pd_on, laser_pd_off = [], []
                    if monos.size > 2:
                        for m in monos:
                            Izero = data_off['I0'].values[data_off['mono'].values == m]
                            Iflo = data_off['If'].values[data_off['mono'].values == m]
                            TF = (~np.isnan(Izero)) * (~np.isnan(Iflo) * (Izero > I0_ll) * (Izero < I0_ul) * (Iflo > If_ll) * (Iflo < If_ul))
                            xas_off.append(Iflo[TF].sum() / Izero[TF].sum())
                            std, N = np.std(Iflo[TF] / Izero[TF]), (TF * 1).sum()
                            err_off.append(std / np.sqrt(N))
                            shots_off.append(N)

                            ######### laser pd ##########
                            sig = data_off[label].values[data_off['mono'].values == m]
                            laser_pd_off.append(np.nanmean(sig[TF]))

                            I0_off.append(Izero[TF].sum())
                            If_off.append(Iflo[TF].sum())

                            Izero = data_on['I0'].values[data_on['mono'].values == m]
                            Iflo = data_on['If'].values[data_on['mono'].values == m]
                            TF = (~np.isnan(Izero)) * (~np.isnan(Iflo) * (Izero > I0_ll) * (Izero < I0_ul) * (Iflo > If_ll) * (Iflo < If_ul))
                            xas_on.append(Iflo[TF].sum() / Izero[TF].sum())
                            std, N = np.std(Iflo[TF] / Izero[TF]), (TF * 1).sum()
                            err_on.append(std / np.sqrt(N))
                            shots_on.append(N)

                            ######### laser pd ##########
                            sig = data_on[label].values[data_on['mono'].values == m]
                            laser_pd_on.append(np.nanmean(sig[TF]))

                            I0_on.append(Izero[TF].sum())
                            If_on.append(Iflo[TF].sum())

                        xas_off = np.array(xas_off)
                        xas_on = np.array(xas_on)
                        err_off = np.array(err_off)
                        err_on = np.array(err_on)

                        I0_on, I0_off, If_on, If_off = np.array(I0_on), np.array(I0_off), np.array(If_on), np.array(If_off)

                        """ Save plots uing matplotlib """

                        for _ax in [self.ax[0],self.ax[1],self.ax2, self.ax3]:
                            _ax.clear()
                        self.ax[0].set_title('XAS')
                        self.ax[0].set_xlabel('Energy /eV')
                        self.ax[0].set_ylabel('XAS')
                        self.ax2.set_ylabel('$\Delta$XAS')
                        self.ax[0].plot(CC2Eng(monos), xas_off, '-o', markersize=2, label='Off')
                        self.ax[0].plot(CC2Eng(monos), xas_on, '-o', markersize=2, label='On')
                        self.ax2.plot(CC2Eng(monos), xas_on-xas_off, '-o', color='C2', markersize=2, label='dif')
                        self.ax[1].set_title('Intensity')
                        self.ax[1].set_xlabel('Energy /eV')
                        self.ax[1].set_ylabel('I0')
                        self.ax3.set_ylabel('If')
                        self.ax[1].plot(CC2Eng(monos), I0_off, linewidth=2,label='I0: off')
                        self.ax[1].plot(CC2Eng(monos), I0_on, linewidth=2,label='I0: on')
                        self.ax3.plot(CC2Eng(monos), If_off,linewidth=2,color='C7', label='If: off')
                        self.ax3.plot(CC2Eng(monos), If_on,linewidth=2,color='C3', label='If: on')
                        self.fig.tight_layout()
                        self.fig.savefig(self.path_to_data + '/' + f'r{self.current_rnum}_escan.png')

                        pd.DataFrame(
                            {
                                '#CC': monos,
                                'Energy': CC2Eng(monos),
                                'xas_on': xas_on,
                                'xas_off': xas_off,
                                'err_on': err_on,
                                'err_off': err_off,
                                'num_shots_on': np.array(shots_on),
                                'num_shots_off': np.array(shots_off),
                                'I0_on': I0_on,
                                'I0_off': I0_off,
                                'If_on': If_on,
                                'If_off': If_off,
                                'laser_pd_on': np.array(laser_pd_on),
                                'laser_pd_off': np.array(laser_pd_off),
                            }
                        ).to_csv(self.path_to_data + '/' + f'r{self.current_rnum}_escan.csv', sep=' ', index=False)

                    else:
                        motor_names = [_m.replace('xfel_bl_3_st_2_', '') for _m in motors]
                        idx = np.argmax(len_motor_values)
                        m_label = motor_names[idx]
                        for m in motor_values[idx]:
                            Izero = data_off['I0'].values[data_off[m_label].values == m]
                            Iflo = data_off['If'].values[data_off[m_label].values == m]
                            TF = (~np.isnan(Izero)) * (~np.isnan(Iflo) * (Izero > I0_ll) * (Izero < I0_ul) * (Iflo > If_ll) * (Iflo < If_ul))
                            xas_off.append(Iflo[TF].sum() / Izero[TF].sum())
                            std, N = np.std(Iflo[TF] / Izero[TF]), (TF * 1).sum()
                            err_off.append(std / np.sqrt(N))
                            shots_off.append(N)

                            I0_off.append(Izero[TF].sum())
                            If_off.append(Iflo[TF].sum())

                            ######### laser pd ##########
                            sig = data_off[label].values[data_off[m_label].values == m]

                            laser_pd_off.append(np.nanmean(sig[TF]))

                            Izero = data_on['I0'].values[data_on[m_label].values == m]
                            Iflo = data_on['If'].values[data_on[m_label].values == m]
                            TF = (~np.isnan(Izero)) * (~np.isnan(Iflo) * (Izero > I0_ll) * (Izero < I0_ul) * (Iflo > If_ll) * (Iflo < If_ul))
                            xas_on.append(Iflo[TF].sum() / Izero[TF].sum())
                            std, N = np.std(Iflo[TF] / Izero[TF]), (TF * 1).sum()
                            err_on.append(std / np.sqrt(N))
                            shots_on.append(N)

                            I0_on.append(Izero[TF].sum())
                            If_on.append(Iflo[TF].sum())

                            ######### laser pd ##########
                            sig = data_on[label].values[data_on[m_label].values == m]
                            laser_pd_on.append(np.nanmean(sig[TF]))

                        xas_off = np.array(xas_off)
                        xas_on = np.array(xas_on)
                        err_off = np.array(err_off)
                        err_on = np.array(err_on)

                        print(sig)

                        I0_on, I0_off, If_on, If_off = np.array(I0_on),np.array(I0_off),np.array(If_on),np.array(If_off)

                        xvalues = motor_values[np.argmax(len_motor_values)]

                        """ Save plots uing matplotlib """
                        for _ax in [self.ax[0],self.ax[1],self.ax2, self.ax3]:
                            _ax.clear()
                        self.ax[0].set_title('XAS')
                        self.ax[0].set_xlabel('motor /pls')
                        self.ax[0].set_ylabel('XAS')
                        self.ax2.set_ylabel('$\Delta$XAS')
                        self.ax[0].plot(xvalues, xas_off, '-o', markersize=2, label='Off')
                        self.ax[0].plot(xvalues, xas_on, '-o', markersize=2, label='On')
                        self.ax2.plot(xvalues, xas_on-xas_off, '-o', color='C2', markersize=2, label='dif')
                        self.ax[1].set_title('Intensity')
                        self.ax[1].set_xlabel('motor /pls')
                        self.ax[1].set_ylabel('I0')
                        self.ax3.set_ylabel('If')
                        self.ax[1].plot(xvalues, I0_off, linewidth=2,label='I0: off')
                        self.ax[1].plot(xvalues, I0_on, linewidth=2,label='I0: on')
                        self.ax3.plot(xvalues, If_off,linewidth=2,color='C7', label='If: off')
                        self.ax3.plot(xvalues, If_on,linewidth=2,color='C3', label='If: on')
                        self.fig.tight_layout()
                        self.fig.savefig(self.path_to_data + '/' + f'r{self.current_rnum}_mscan.png')

                        pd.DataFrame(
                            {
                                '#motor': xvalues,
                                'xas_on': xas_on,
                                'xas_off': xas_off,
                                'err_on': err_on,
                                'err_off': err_off,
                                'num_shots_on': np.array(shots_on),
                                'num_shots_off': np.array(shots_off),
                                'I0_on': I0_on,
                                'I0_off': I0_off,
                                'If_on': If_on,
                                'If_off': If_off,
                                'laser_pd_on': np.array(laser_pd_on),
                                'laser_pd_off': np.array(laser_pd_off),
                            }
                        ).to_csv(self.path_to_data + '/' + f'r{self.current_rnum}_mscan.csv',
                                 sep=' ', index=False)
                    self.u.textBrowser_2.append(f"     >>>>>>>>>> Post processing: {time.time() - stime: .1f} s <<<<<<<<<<")

                    if self.u.checkBox.isChecked():
                        monos = np.unique(data_on['mono'].values)
                        motor_values = np.array(
                            [np.unique(data_on[_m.replace('xfel_bl_3_st_2_', '')].values) for _m in motors])
                        len_motor_values = np.array([arr.size for arr in motor_values])

                        xas_on, xas_off, err_on, err_off = [], [], [], []
                        I0_on, I0_off, If_on, If_off, shots_on, shots_off = [], [], [], [], [], []
                        laser_pd_on, laser_pd_off = [], []
                        if monos.size > 2:
                            for m in monos:
                                Izero = data_off['I0'].values[data_off['mono'].values == m]
                                Iflo = data_off['mpccd'].values[data_off['mono'].values == m]
                                TF = (~np.isnan(Izero)) * (Izero > I0_ll) * (Izero < I0_ul)
                                xas_off.append(Iflo[TF].sum() / Izero[TF].sum())
                                std, N = np.std(Iflo[TF] / Izero[TF]), (TF * 1).sum()
                                err_off.append(std / np.sqrt(N))
                                shots_off.append(N)

                                ######### laser pd ##########
                                sig = data_off[label].values[data_off['mono'].values == m]
                                laser_pd_off.append(np.nanmean(sig[TF]))

                                I0_off.append(Izero[TF].sum())
                                If_off.append(Iflo[TF].sum())

                                Izero = data_on['I0'].values[data_on['mono'].values == m]
                                Iflo = data_on['mpccd'].values[data_on['mono'].values == m]
                                TF = (~np.isnan(Izero)) * (Izero > I0_ll) * (Izero < I0_ul)
                                xas_on.append(Iflo[TF].sum() / Izero[TF].sum())
                                std, N = np.std(Iflo[TF] / Izero[TF]), (TF * 1).sum()
                                err_on.append(std / np.sqrt(N))
                                shots_on.append(N)
                                ######### laser pd ##########
                                sig = data_on[label].values[data_on['mono'].values == m]
                                laser_pd_on.append(np.nanmean(sig[TF]))

                                I0_on.append(Izero[TF].sum())
                                If_on.append(Iflo[TF].sum())

                            xas_off = np.array(xas_off)
                            xas_on = np.array(xas_on)
                            err_off = np.array(err_off)
                            err_on = np.array(err_on)

                            I0_on, I0_off, If_on, If_off = np.array(I0_on), np.array(I0_off), np.array(If_on), np.array(If_off)

                            """ Save plots uing matplotlib """

                            for _ax in [self.ax[0], self.ax[1], self.ax2, self.ax3]:
                                _ax.clear()
                            self.ax[0].set_title('XAS')
                            self.ax[0].set_xlabel('Energy /eV')
                            self.ax[0].set_ylabel('XAS')
                            self.ax2.set_ylabel('$\Delta$XAS')
                            self.ax[0].plot(CC2Eng(monos), xas_off, '-o', markersize=2, label='Off')
                            self.ax[0].plot(CC2Eng(monos), xas_on, '-o', markersize=2, label='On')
                            self.ax2.plot(CC2Eng(monos), xas_on - xas_off, '-o', color='C2', markersize=2, label='dif')
                            self.ax[1].set_title('Intensity')
                            self.ax[1].set_xlabel('Energy /eV')
                            self.ax[1].set_ylabel('I0')
                            self.ax3.set_ylabel('If')
                            self.ax[1].plot(CC2Eng(monos), I0_off, linewidth=2, label='I0: off')
                            self.ax[1].plot(CC2Eng(monos), I0_on, linewidth=2, label='I0: on')
                            self.ax3.plot(CC2Eng(monos), If_off, linewidth=2, color='C7', label='If: off')
                            self.ax3.plot(CC2Eng(monos), If_on, linewidth=2, color='C3', label='If: on')
                            self.fig.tight_layout()
                            self.fig.savefig(self.path_to_data + '/' + f'r{self.current_rnum}_escan_mpccd.png')

                            pd.DataFrame(
                                {
                                    '#CC': monos,
                                    'Energy': CC2Eng(monos),
                                    'xas_on': xas_on,
                                    'xas_off': xas_off,
                                    'err_on': err_on,
                                    'err_off': err_off,
                                    'num_shots_on': np.array(shots_on),
                                    'num_shots_off': np.array(shots_off),
                                    'I0_on': I0_on,
                                    'I0_off': I0_off,
                                    'If_on': If_on,
                                    'If_off': If_off,
                                    'laser_pd_on': np.array(laser_pd_on),
                                    'laser_pd_off': np.array(laser_pd_off),
                                }
                            ).to_csv(self.path_to_data + '/' + f'r{self.current_rnum}_escan_mpccd.csv', sep=' ', index=False)

                        else:
                            motor_names = [_m.replace('xfel_bl_3_st_2_', '') for _m in motors]
                            idx = np.argmax(len_motor_values)
                            m_label = motor_names[idx]
                            for m in motor_values[idx]:
                                Izero = data_off['I0'].values[data_off[m_label].values == m]
                                Iflo = data_off['mpccd'].values[data_off[m_label].values == m]
                                TF = (~np.isnan(Izero)) * (Izero > I0_ll) * (Izero < I0_ul)
                                xas_off.append(Iflo[TF].sum() / Izero[TF].sum())
                                std, N = np.std(Iflo[TF] / Izero[TF]), (TF * 1).sum()
                                err_off.append(std / np.sqrt(N))
                                shots_off.append(N)

                                I0_off.append(Izero[TF].sum())
                                If_off.append(Iflo[TF].sum())

                                ######### laser pd ##########
                                sig = data_off[label].values[data_off[m_label].values == m]

                                laser_pd_off.append(np.nanmean(sig[TF]))

                                Izero = data_on['I0'].values[data_on[m_label].values == m]
                                Iflo = data_on['mpccd'].values[data_on[m_label].values == m]
                                TF = (~np.isnan(Izero)) * (Izero > I0_ll) * (Izero < I0_ul)
                                xas_on.append(Iflo[TF].sum() / Izero[TF].sum())
                                std, N = np.std(Iflo[TF] / Izero[TF]), (TF * 1).sum()
                                err_on.append(std / np.sqrt(N))
                                shots_on.append(N)

                                I0_on.append(Izero[TF].sum())
                                If_on.append(Iflo[TF].sum())

                                ######### laser pd ##########
                                sig = data_on[label].values[data_on[m_label].values == m]
                                laser_pd_on.append(np.nanmean(sig[TF]))

                            xas_off = np.array(xas_off)
                            xas_on = np.array(xas_on)
                            err_off = np.array(err_off)
                            err_on = np.array(err_on)

                            print(sig)

                            I0_on, I0_off, If_on, If_off = np.array(I0_on), np.array(I0_off), np.array(If_on), np.array(If_off)

                            xvalues = motor_values[np.argmax(len_motor_values)]

                            """ Save plots uing matplotlib """
                            for _ax in [self.ax[0], self.ax[1], self.ax2, self.ax3]:
                                _ax.clear()
                            self.ax[0].set_title('XAS')
                            self.ax[0].set_xlabel('motor /pls')
                            self.ax[0].set_ylabel('XAS')
                            self.ax2.set_ylabel('$\Delta$XAS')
                            self.ax[0].plot(xvalues, xas_off, '-o', markersize=2, label='Off')
                            self.ax[0].plot(xvalues, xas_on, '-o', markersize=2, label='On')
                            self.ax2.plot(xvalues, xas_on - xas_off, '-o', color='C2', markersize=2, label='dif')
                            self.ax[1].set_title('Intensity')
                            self.ax[1].set_xlabel('motor /pls')
                            self.ax[1].set_ylabel('I0')
                            self.ax3.set_ylabel('If')
                            self.ax[1].plot(xvalues, I0_off, linewidth=2, label='I0: off')
                            self.ax[1].plot(xvalues, I0_on, linewidth=2, label='I0: on')
                            self.ax3.plot(xvalues, If_off, linewidth=2, color='C7', label='If: off')
                            self.ax3.plot(xvalues, If_on, linewidth=2, color='C3', label='If: on')
                            self.fig.tight_layout()
                            self.fig.savefig(self.path_to_data + '/' + f'r{self.current_rnum}_mscan_mpccd.png')

                            pd.DataFrame(
                                {
                                    '#motor': xvalues,
                                    'xas_on': xas_on,
                                    'xas_off': xas_off,
                                    'err_on': err_on,
                                    'err_off': err_off,
                                    'num_shots_on': np.array(shots_on),
                                    'num_shots_off': np.array(shots_off),
                                    'I0_on': I0_on,
                                    'I0_off': I0_off,
                                    'If_on': If_on,
                                    'If_off': If_off,
                                    'laser_pd_on': np.array(laser_pd_on),
                                    'laser_pd_off': np.array(laser_pd_off),
                                }
                            ).to_csv(self.path_to_data + '/' + f'r{self.current_rnum}_mscan_mpccd.csv',
                                     sep=' ', index=False)
                        self.u.textBrowser_2.append(f"     >>>>>>>>>> Post processing (MPCCD): {time.time() - stime: .1f} s <<<<<<<<<<")

            self.current_rnum = value
        except Exception as e:
            self.client.stop()
            self.u.pB_run.toggle()
            exc_type, exc_obj, exc_tb = sys.exc_info()
            linenumber = exc_tb.tb_lineno
            msg(f'Line {linenumber}: {str(e)}')

    def start_stop_client(self):
        print (self.client.is_active)
        if self.client.is_active:
            self.client.stop()
        else:
            if not os.path.isdir(self.u.textBrowser.toPlainText()):
                msg('Please set the output path')
                self.u.pB_run.toggle()
                return
            else:
                BL = self.u.sB_BL.value()
                run_start, run_end = self.u.sB_RN_start.value(), self.u.sB_RN_end.value()
                device_list = ['xfel_bl_3_st_1_motor_3/position']
                device_list += [self.motorlist[self.u.listWidget.item(n).text()] + '/position' for n in
                                range(self.u.listWidget.count()) if self.u.listWidget.item(n).isSelected()]
                device_list += [f'xfel_bl_3_st_2_pd_user_{j}_fitting_peak/voltage' for j in range(1, 16) if getattr(self.u, f"pdI0_{j}").isChecked()] + \
                               [f'xfel_bl_3_st_2_pd_user_{j}_fitting_peak/voltage' for j in range(1, 16) if getattr(self.u, f"pdI_{j}").isChecked()]
                device_list += [self.laser_pd]
                print (device_list)
                self.num_pdlist = [j for j in range(1, 16) if getattr(self.u, f"pdI0_{j}").isChecked()] + \
                                  [j for j in range(1, 16) if getattr(self.u, f"pdI_{j}").isChecked()]
                outpath = self.u.textBrowser.toPlainText()
                self.current_rnum = self.u.sB_RN_start.value()
                self.client.set_endpoint(run_start,run_end,device_list,outpath)
                if self.u.checkBox.isChecked():
                    self.client.setMPCCD(True,self.u.lineEdit_2.text(),f'{self.PROGRAMDIR}/mpccd_bg.npy')

                self.u.textBrowser_2.clear()
                self.client.start()

if __name__ == '__main__':
    window = MainWindow()
    sys.exit(app.exec_())
