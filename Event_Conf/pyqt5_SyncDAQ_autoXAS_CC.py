import sys, os, string, io, glob, re, yaml, math, time
import numpy as np
import pandas as pd
import shutil
import subprocess as sub

import silx
from silx.gui import qt
app = qt.QApplication([])
import time
import silx.gui.colors as silxcolors
from silx.gui.plot import Plot1D

def CC2Eng(M):
    theta = M*4/10**6
    return 12.3984/(6.270832*np.sin(theta*np.pi/180.0))*1000

def msg(txt):
    _msg = qt.QMessageBox()
    _msg.setIcon(qt.QMessageBox.Warning)
    _msg.setText(txt)
    _msg.setStandardButtons(qt.QMessageBox.Ok)
    return _msg

try:
    import dbpy
    import stpy
except:
    msg('Fialed to import dbpy').exec_()
    sys.exit()

HOMEDIR = os.environ['HOME']
PYDIR = HOMEDIR+'/python'
PROGRAMDIR =  PYDIR+'/py_SyncDAQ_autoXAS_CC_dev'

wHDF5 = '/work/uemura/mpccd/hdf5'

#####read configulation file of SACLA equipments#####
Equipments_in_SACLA = yaml.load(open(PROGRAMDIR+'/SACLA_equiplist.txt'),Loader=yaml.Loader)['SACLA_eq_list']

from Ui_SyncDAQ_XASauto import Ui_MainWindow

class MainWindow(qt.QMainWindow):
    def __init__(self):
        # QtGui.QMainWindow.__init__(self,parent)
        super(self.__class__, self).__init__()
        self.u = Ui_MainWindow()
        self.u.setupUi(self)
        self.eqid = [True,True,True]
        self.motorlist = yaml.load(open(PROGRAMDIR+'/motorlist.yaml'),Loader=yaml.Loader)['eqid']
        self.eqid_ud = [ x +'/position' in Equipments_in_SACLA for x in self.motorlist]
        
        self.timer = qt.QTimer()

        self.dbmonochro = 'xfel_bl_3_st_1_motor_3/position'
        self.confdir = PROGRAMDIR+'/Event_Conf'
        
        self.u.progressBar.setMaximum(self.u.sB_RN_end.value())
        self.u.progressBar.setMinimum(self.u.sB_RN_start.value())
        self.u.progressBar.setValue(self.u.progressBar.minimum())
        self.runNumber = self.u.sB_RN_start.value()
        self.runNumber_max = self.u.sB_RN_end.value()

        ############ Plotters ############
        self.plot_xas = Plot1D()
        self.plot_intensity = Plot1D()
        
        layout = qt.QVBoxLayout()
        self.u.widget.setLayout(layout)
        layout.addWidget(self.plot_xas)
        
        layout = qt.QVBoxLayout()
        self.u.widget_2.setLayout(layout)
        layout.addWidget(self.plot_intensity)
        
        ############ Select defaultPDs ##########
        self.u.I0_pds.item(13).setSelected(True)
        self.u.I0_pds.item(14).setSelected(True)
        self.u.If_pds.item(12).setSelected(True)


        def chooseDatDir():
            _dir = self.u.textBrowser.toPlainText()
            self.u.textBrowser.clear()
            basedir = HOMEDIR
            if os.path.isdir(_dir):
                basedir = _dir

            datdir = qt.QFileDialog.getExistingDirectory(None, 'Select a folder:',
                                                            basedir, qt.QFileDialog.ShowDirsOnly)
            self.u.textBrowser.append(datdir.rstrip())
        def setvalue_start_number(value):
            self.runNumber = value
            #print (self.runnumber)
        def setvalue_end_number(value):
            self.runNumber_max = value
        self.u.pB_path.clicked.connect(chooseDatDir)
        self.u.sB_RN_start.valueChanged[int].connect(self.u.sB_RN_end.setMinimum)
        self.u.sB_RN_start.valueChanged[int].connect(self.u.progressBar.setMinimum)
        self.u.sB_RN_start.valueChanged[int].connect(self.u.progressBar.setValue)
        self.u.sB_RN_end.valueChanged[int].connect(self.u.progressBar.setMaximum)
        self.u.sB_RN_start.valueChanged[int].connect(setvalue_start_number)
        self.u.sB_RN_end.valueChanged[int].connect(setvalue_end_number)
        
        
        self.u.pB_run.clicked.connect(self.doAction)
        
        self.show()

    def doAction(self):
        if self.timer.isActive():
            self.timer.stop()
            self.u.progressBar.setValue(self.u.progressBar.maximum())
            self.u.pB_run.setText('Run')
            self.runNumber = self.u.progressBar.minimum()
            if os.path.isfile(PROGRAMDIR+'/curent_status.txt'):
               os.remove(PROGRAMDIR+'/curent_status.txt')
        else:
            if os.path.isdir(self.u.textBrowser.toPlainText()):
                self.BL = self.u.sB_BL.value()
                print ([_item.text() for _item in self.u.I0_pds.selectedItems()])
            else:
                msg('Output is not set').exec_()
                
                # self.num_pdlist = [int(x.replace(' ','')) for x in self.u.lE_PDs_I0.text().rstrip().split(',')]
            #     self.num_pdlist += [int(x.replace(' ', '')) for x in self.u.lE_PDs_If.text().rstrip().split(',')]

            #     self.path_to_data = self.u.textBrowser.toPlainText()
            #     d = {'PATH_to_DATA':self.path_to_data,
            #          # 'Photodiodes':{'I0_1':self.name_i0_1,'I0_2':self.name_i0_2,'If':self.name_if},
            #          'MeasurementType':self.u.cB_type.currentText(),
            #          'Motor':self.eqid,
            #          'w/wo_Laser':str(self.u.checkBox_wLaser.isChecked())
            #          }
            #     d['Photodiodes'] = {}
            #     d['Photodiodes']['I0'] = [int(x.replace(' ','')) for x in self.u.lE_PDs_I0.text().rstrip().split(',')]
            #     d['Photodiodes']['If'] = [int(x.replace(' ', '')) for x in self.u.lE_PDs_If.text().rstrip().split(',')]
            #     with open(PROGRAMDIR+'/current_status.yaml', 'w') as yaml_file:
            #         yaml.dump(d, yaml_file, default_flow_style=False)
            #     yaml_file.close()
            #     confdict = {}
            #     for key in d.keys():
            #         confdict[key] = d[key]
            #     with open(self.path_to_data+'/measurement_status.yaml', 'w') as yaml_file:
            #         yaml.dump(confdict, yaml_file, default_flow_style=False)
            #     if not os.path.isdir(self.path_to_data+'/Taglist'):
            #         os.mkdir(self.path_to_data+'/Taglist')
            #     self.starttime = time.time()
            #     self.timer.start(100, self)
            #     self.u.pB_run.setText('Stop')
            # else:
            #     QtWidgets.QMessageBox.about(self, "!! PATH is missing !!", "Please check the path for outputs")

if __name__ == '__main__':
    wid = MainWindow()
    wid.setWindowTitle('SyncDAQ_autoXAS')
    sys.exit(app.exec_())
