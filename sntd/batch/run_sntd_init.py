import pickle,sys,sntd,os,traceback
from optparse import OptionParser
from copy import copy
import numpy as np
import tarfile

njobs=njobsreplace
nlcs=nlcsreplace
parser = OptionParser()

(options,args)=parser.parse_args()

batchinitreplace

all_dat=pickle.load(open(os.path.join(os.path.abspath(os.path.dirname(__file__)),
                                      'sntd_data.pkl'),'rb'))
all_const=pickle.load(open(os.path.join(os.path.abspath(os.path.dirname(__file__)),
                                        'sntd_constants.pkl'),'rb'))

inds=[int(nlcs/njobs)*int(sys.argv[1]),int(nlcs/njobs)*int(sys.argv[1])+int(nlcs/njobs)]
inds[1]=min(inds[-1],len(all_dat))

all_res=[]
for i in range(inds[0],inds[1]):
    if isinstance(all_dat[i],str):
        all_dat[i]=pickle.load(open(all_dat[i],'rb'))
    all_dat[i].constants={}
    if all_const is not None:
        for c in all_const.keys():
            if isinstance(all_const[c],(list,tuple,np.ndarray)):
                all_dat[i].constants[c]=all_const[c][i]
            else:
                all_dat[i].constants[c]=all_const[c]
    try:
        fitCurves=sntdcommandreplace
        all_res.append(copy(fitCurves))
    except Exception as e:
        print('Failed')
        print(traceback.format_exc())
        all_res.append(None)

filename=os.path.join(os.path.abspath(os.path.dirname(__file__)),'sntd_fit%s.pkl'%sys.argv[1])
pickle.dump(all_res,open(filename,'wb'))
opened=False
tried=0
while not opened:
    try:
        out=tarfile.open('sntd_fits.tar.gz','a')
        out.add(filename)
        out.close()
        opened=True
    except:
        opened=False
    tried+=1
    if tried>100:
        break
if opened:
    os.remove(filename)

