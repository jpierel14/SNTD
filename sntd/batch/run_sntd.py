import pickle,sys,sntd,os
from optparse import OptionParser
from copy import copy

nlcs_per=nlcsreplace
parser = OptionParser()

(options,args)=parser.parse_args()

batchinitreplace

all_dat=pickle.load(open(os.path.join(os.path.abspath(os.path.dirname(__file__)),
                                      'sntd_data.pkl'),'rb'))
inds=[int(int(sys.argv[1])*nlcs_per),(int(sys.argv[1])+1)*int(nlcs_per)]
inds[1]=min(inds[-1],len(all_dat))

all_res=[]
for i in range(inds[0],inds[1]):
    try:
        fitCurves=sntdcommandreplace
        all_res.append(copy(fitCurves))
    except:
        all_res.append(None)

pickle.dump(all_res,open(os.path.join(os.path.abspath(os.path.dirname(__file__)),'sntd_fit%s.pkl'%sys.argv[1]),'wb'))
